import os
import re
import yaml
import logging
import tiktoken
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.call_llm import call_llm, get_model_context_length
from utils.crawl_local_files import crawl_local_files
from utils.token_utils import log_token_estimation
from collections import defaultdict


# Helper to get content for specific file indices
def get_content_for_indices(files_data, indices):
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = (
                content  # Use index + path as key for context
            )
    return content_map


# --- Reusable Helpers ---

def load_prompt_template(template_name, advanced_mode=False, mode=None):
    """Load a prompt template file from the prompts/ directory."""
    if mode is None:
        prompt_dir = "advanced" if advanced_mode else "tutorial"
    else:
        prompt_dir = mode
        
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "prompts", prompt_dir, f"{template_name}.md")
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def parse_yaml_response(response):
    """Extract and parse YAML from an LLM response fenced in ```yaml blocks."""
    try:
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        return yaml.safe_load(yaml_str)
    except Exception as e:
        raise ValueError(f"Failed to parse YAML: {e}")


def create_token_counter():
    """Create a token counting function using tiktoken with char-count fallback."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(enc.encode(text, disallowed_special=()))
    except Exception:
        return lambda text: len(text) // 4


def resolve_max_tokens(shared):
    """Resolve max_tokens from shared store or auto-detect from provider env vars."""
    max_tokens = shared.get("max_tokens")
    if max_tokens is not None:
        return max_tokens
    provider = os.environ.get("LLM_PROVIDER")
    if provider == "GEMINI" or not provider:
        endpoint = "https://generativelanguage.googleapis.com"
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
        api_key = os.getenv("GEMINI_API_KEY", "")
    else:
        endpoint = os.environ.get(f"{provider}_BASE_URL", "")
        model_name = os.environ.get(f"{provider}_MODEL", "")
        api_key = os.environ.get(f"{provider}_API_KEY", "")
    return get_model_context_length(endpoint, model_name, api_key)



class DeterministicFileMapper(Node):
    def prep(self, shared):
        files_data = shared["files"]
        project_name = shared["project_name"]
        
        file_listing = "\n".join([f"{i} # {path}" for i, (path, _) in enumerate(files_data)])
        
        prompt = f"""For the project `{project_name}`, here is the list of all files in the codebase:

{file_listing}

Your task is to identify WHICH of these files are ACTUAL CODE files that contain APIs, functions, classes, or core business logic.
EXCLUDE: UI layouts (like .xaml, .storyboard, .html), configuration files (like .xml, .json, .manifest, .ini), static assets, build scripts (like .csproj, .sln), and documentation.

Return ONLY a YAML list of the file indices that should be documented as code modules.

```yaml
- 0
- 1
- 3
```"""
        return prompt, shared.get("thinking_level", None), shared.get("max_tokens", 100000)

    def exec(self, prep_res):
        try:
            prompt, thinking_level, max_tokens = prep_res
            log_token_estimation(self.__class__.__name__, prompt, max_tokens)
            print(f"Smartly filtering non-code files using LLM...")
            response = call_llm(prompt, use_cache=True, thinking_level=thinking_level)
            valid_indices = parse_yaml_response(response)
            if not isinstance(valid_indices, list):
                valid_indices = []
            return [int(idx) for idx in valid_indices]
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res):
        import os
        files = shared.get("files", [])
        valid_indices = set(exec_res)
        modules = []
        chapter_order = []
        
        for idx, (file_path, content) in enumerate(files):
            if idx not in valid_indices:
                print(f"  - Skipping non-code file: {file_path}")
                continue
                
            clean_name = os.path.splitext(file_path)[0].replace(os.sep, ".").replace("/", ".")
            
            modules.append({
                "name": clean_name,
                "description": f"Internal API reference for `{file_path}`",
                "files": [idx],
                "original_path": file_path
            })
            chapter_order.append(len(modules) - 1)
            
        shared["abstractions"] = modules
        shared["chapter_order"] = chapter_order
        shared["relationships"] = {"summary": "Deterministic Internal API Reference.", "details": []}
        print(f"\033[92m[DeterministicFileMapper] Mapped {len(modules)} ACTUAL code files for exhaustive documentation.\033[0m")
        return "default"

class ContextRouter(Node):
    def prep(self, shared):
        files_data = shared["files"]
        max_tokens = resolve_max_tokens(shared)
        
        shared["max_tokens"] = max_tokens
        
        # --- Token estimation setup ---
        count_tokens = create_token_counter()

        # --- Calculate prompt overhead FIRST ---
        # 1. Prompt template (measure both, use the larger)
        prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
        max_template_tokens = 0
        for subdir in ["tutorial", "advanced"]:
            template_path = os.path.join(prompt_dir, subdir, "map_abstractions.md")
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8-sig") as f:
                    t = count_tokens(f.read())
                max_template_tokens = max(max_template_tokens, t)

        # 2. Directory tree (built from all files, shared across batches)
        directory_tree = self._build_directory_tree(files_data)
        tree_tokens = count_tokens(directory_tree)

        prompt_overhead = max_template_tokens + tree_tokens
        print(f"\033[93m[ContextRouter] Prompt overhead: ~{prompt_overhead:,} tokens "
              f"(template: {max_template_tokens:,}, dir tree: {tree_tokens:,})\033[0m")

        # --- Count file content tokens ---
        total_tokens = 0
        file_token_map = []
        for i, (path, content) in enumerate(files_data):
            entry = f"--- File Index {i}: {path} ---\n{content}\n\n"
            tokens = count_tokens(entry)
            total_tokens += tokens
            file_token_map.append(tokens)

        # --- Effective limit = safety margin minus overhead ---
        safety_limit = int(max_tokens * 0.95)
        effective_limit = safety_limit - prompt_overhead
        force_batch = shared.get("force_batch", False)
        
        if shared.get("mode", "tutorial") == "api-reference":
            print(f"\033[92m[ContextRouter] api-reference mode active. Bypassing LLM discovery and routing to DeterministicFileMapper.\033[0m")
            return ("deterministic", files_data, effective_limit, shared.get("batch_size", 50),
                    None, None, directory_tree, False)

        if total_tokens > effective_limit and force_batch:
            print(f"\033[93m[ContextRouter] File content ({total_tokens:,} tokens) exceeds effective limit "
                  f"({effective_limit:,} = {safety_limit:,} - {prompt_overhead:,} overhead) "
                  f"and --force-batch is set. Using Map-Reduce.\033[0m")
        elif total_tokens > effective_limit:
            print(f"\033[93m[ContextRouter] File content ({total_tokens:,} tokens) exceeds effective limit "
                  f"({effective_limit:,} = {safety_limit:,} - {prompt_overhead:,} overhead). "
                  f"Using Map-Reduce.\033[0m")
        elif force_batch:
            print(f"\033[93m[ContextRouter] File content ({total_tokens:,} tokens) fits in effective limit "
                  f"({effective_limit:,} = {safety_limit:,} - {prompt_overhead:,} overhead) "
                  f"but --force-batch is set. Using Map-Reduce.\033[0m")
        else:
            print(f"\033[92m[ContextRouter] File content ({total_tokens:,} tokens) fits in effective limit "
                  f"({effective_limit:,} = {safety_limit:,} - {prompt_overhead:,} overhead). "
                  f"Proceeding normally.\033[0m")
            return ("direct", files_data, effective_limit, shared.get("batch_size", 50),
                    None, None, directory_tree, False)

        return ("batch", files_data, effective_limit, shared.get("batch_size", 50),
                file_token_map, count_tokens, directory_tree, shared.get("debug", False))

    def exec(self, prep_res):
        route, files_data, effective_limit, batch_size, file_token_map, count_tokens, directory_tree, debug = prep_res
        if route == "direct":
            return "direct"
        if route == "deterministic":
            return "deterministic"

        # Group by directory for coherence, with pre-computed tokens
        dir_groups = defaultdict(list)
        for i, (path, content) in enumerate(files_data):
            dir_groups[os.path.dirname(path)].append((i, path, content, file_token_map[i]))

        # Build token-aware batches (never mix directories)
        batches = []
        for dirname in sorted(dir_groups.keys()):
            current_batch = []
            current_tokens = 0

            for i, path, content, tokens in dir_groups[dirname]:
                # Start new batch if adding this file would exceed effective limit or file count cap
                if current_batch and (current_tokens + tokens > effective_limit or len(current_batch) >= batch_size):
                    batches.append(current_batch)
                    current_batch = []
                    current_tokens = 0

                current_batch.append((i, path, content))
                current_tokens += tokens

            # Flush remaining files in this directory
            if current_batch:
                batches.append(current_batch)

        batch_word = "batch" if len(batches) == 1 else "batches"
        print(f"\033[93m[ContextRouter] Split into {len(batches)} {batch_word}.\033[0m")

        # Debug: show detailed batch info
        if debug:
            C_GREEN = "\033[92m"
            C_RESET = "\033[0m"
            for idx, batch in enumerate(batches):
                content_tokens = sum(file_token_map[i] for i, p, c in batch)
                print(f"\033[93m  [Debug] Batch {idx}: {len(batch)} files, "
                      f"~{content_tokens:,} content tokens (limit: {effective_limit:,})\033[0m")
                for i, p, c in batch:
                    print(f"{C_GREEN}    - [{i}] {p}{C_RESET}")

        # Store directory tree for later use
        self._directory_tree = directory_tree
            
        return batches

    def post(self, shared, prep_res, exec_res):
        if exec_res == "direct":
            return "direct"
        if exec_res == "deterministic":
            return "deterministic"
        shared["file_batches"] = exec_res
        # Reuse directory tree built during prep()
        shared["directory_tree"] = getattr(self, "_directory_tree", self._build_directory_tree(shared["files"]))
        return "batch"

    @staticmethod
    def _build_directory_tree(files_data):
        """Build a compact directory tree string from the list of (path, content) tuples."""
        from collections import defaultdict
        dir_files = defaultdict(list)
        for i, (path, _content) in enumerate(files_data):
            dirname = os.path.dirname(path) or "."
            basename = os.path.basename(path)
            dir_files[dirname].append(f"{basename} (idx:{i})")

        lines = []
        for dirname in sorted(dir_files.keys()):
            lines.append(f"{dirname}/")
            for fname in sorted(dir_files[dirname]):
                lines.append(f"  {fname}")
        return "\n".join(lines)


class MapAbstractions(BatchNode):
    def prep(self, shared):
        return [
            {
                "batch_index": i,
                "files": batch,
                "project_name": shared["project_name"],
                "language": shared.get("language", "english"),
                "use_cache": shared.get("use_cache", True),
                "thinking_level": shared.get("thinking_level", None),
                "advanced_mode": shared.get("advanced_mode", False),
                "max_tokens": shared.get("max_tokens", 100000),
                "directory_tree": shared.get("directory_tree", "")
            }
            for i, batch in enumerate(shared["file_batches"])
        ]

    def exec(self, item):
        batch_index = item["batch_index"]
        files = item["files"]
        print(f"Mapping abstractions for batch {batch_index} ({len(files)} files)...")
        
        context = ""
        file_listing_for_prompt = []
        for i, path, content in files:
            context += f"--- File Index {i}: {path} ---\n{content}\n\n"
            file_listing_for_prompt.append(f"- {i} # {path}")
            
        file_listing = "\n".join(file_listing_for_prompt)
        
        prompt_template = load_prompt_template("map_abstractions", mode=item.get("mode", "tutorial"))

        language = item.get("language", "english")
        language_instruction = f"Output language MUST be entirely in {language}. " if language.lower() != "english" else ""
        name_lang_hint = f" (in {language})" if language.lower() != "english" else ""
        desc_lang_hint = f" (in {language})" if language.lower() != "english" else ""

        prompt = prompt_template.format(
            project_name=item["project_name"],
            context=context,
            file_listing_for_prompt=file_listing,
            language_instruction=language_instruction,
            name_lang_hint=name_lang_hint,
            desc_lang_hint=desc_lang_hint,
            directory_tree=item.get("directory_tree", "Not available")
        )
        
        log_token_estimation(self.__class__.__name__, prompt, item["max_tokens"])
        for i, path, _content in files:
            print(f"\033[92m    - [{i}] {path}\033[0m")
        response = call_llm(prompt, use_cache=(item["use_cache"] and self.cur_retry == 0), thinking_level=item["thinking_level"])

        abstractions = parse_yaml_response(response)

        validated_abstractions = []
        if isinstance(abstractions, list):
            for obj in abstractions:
                if isinstance(obj, dict) and "name" in obj and "description" in obj and "file_indices" in obj:
                    import re
                    validated_indices = []
                    for idx_entry in obj["file_indices"]:
                        nums = re.findall(r'\d+', str(idx_entry))
                        if nums:
                            validated_indices.append(int(nums[0]))
                    if validated_indices:
                        validated_abstractions.append({
                            "name": obj["name"],
                            "description": obj["description"],
                            "files": sorted(list(set(validated_indices)))
                        })
        return validated_abstractions

    def post(self, shared, prep_res, exec_res_list):
        all_abstractions = []
        for batch_abs in exec_res_list:
            all_abstractions.extend(batch_abs)
        shared["mapped_abstractions"] = all_abstractions


class ReduceAbstractions(Node):
    def prep(self, shared):
        return (
            shared["mapped_abstractions"],
            shared["project_name"],
            shared.get("language", "english"),
            shared.get("use_cache", True),
            shared.get("max_abstraction_num", 10),
            shared.get("thinking_level", None),
            shared.get("advanced_mode", False),
            shared.get("max_tokens", 100000),
            shared.get("mode", "tutorial")
        )

    def exec(self, prep_res):
        mapped_abstractions, project_name, language, use_cache, max_abstraction_num, thinking_level, advanced_mode, max_tokens, doc_mode = prep_res
        
        context = ""
        for i, abs_obj in enumerate(mapped_abstractions):
            context += f"- Partial Abstraction {i}: {abs_obj['name']}\n  Description: {abs_obj['description']}\n  Files: {abs_obj['files']}\n\n"

        prompt_template = load_prompt_template("reduce_abstractions", mode=doc_mode)
            
        language_instruction = f"Output language MUST be entirely in {language}. " if language.lower() != "english" else ""
        name_lang_hint = f" (in {language})" if language.lower() != "english" else ""
        desc_lang_hint = f" (in {language})" if language.lower() != "english" else ""
        
        prompt = prompt_template.format(
            project_name=project_name,
            partial_abstractions=context,
            max_abstraction_num=max_abstraction_num,
            language_instruction=language_instruction,
            name_lang_hint=name_lang_hint,
            desc_lang_hint=desc_lang_hint
        )
        
        log_token_estimation(self.__class__.__name__, prompt, max_tokens)
        print(f"Reducing {len(mapped_abstractions)} partial abstractions into global architecture...")
        response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)

        abstractions = parse_yaml_response(response)

        validated_abstractions = []
        if isinstance(abstractions, list):
            for obj in abstractions:
                if isinstance(obj, dict) and "name" in obj and "description" in obj and "files" in obj:
                    import re
                    validated_indices = []
                    for idx_entry in obj["files"]:
                        nums = re.findall(r'\d+', str(idx_entry))
                        if nums:
                            validated_indices.append(int(nums[0]))
                    if validated_indices:
                        validated_abstractions.append({
                            "name": obj["name"],
                            "description": obj["description"],
                            "files": sorted(list(set(validated_indices)))
                        })
        return validated_abstractions

    def post(self, shared, prep_res, exec_res):
        shared["abstractions"] = exec_res


class FetchRepo(Node):
    def prep(self, shared):
        repo_url = shared.get("repo_url")
        local_dir = shared.get("local_dir")
        project_name = shared.get("project_name")

        if not project_name:
            # Basic name derivation from URL or directory
            if repo_url:
                project_name = repo_url.split("/")[-1].replace(".git", "")
            else:
                project_name = os.path.basename(os.path.abspath(local_dir))
            shared["project_name"] = project_name

        # Get file patterns directly from shared
        include_patterns = shared["include_patterns"]
        exclude_patterns = shared["exclude_patterns"]
        max_file_size = shared["max_file_size"]

        return {
            "repo_url": repo_url,
            "local_dir": local_dir,
            "token": shared.get("github_token"),
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "max_file_size": max_file_size,
            "use_relative_paths": True,
        }

    def exec(self, prep_res):
        if prep_res["repo_url"]:
            print(f"Crawling repository: {prep_res['repo_url']}...")
            result = crawl_github_files(
                repo_url=prep_res["repo_url"],
                token=prep_res["token"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"],
            )
        else:
            print(f"Crawling directory: {prep_res['local_dir']}...")

            result = crawl_local_files(
                directory=prep_res["local_dir"],
                include_patterns=prep_res["include_patterns"],
                exclude_patterns=prep_res["exclude_patterns"],
                max_file_size=prep_res["max_file_size"],
                use_relative_paths=prep_res["use_relative_paths"]
            )

        # Convert dict to list of tuples: [(path, content), ...]
        files_list = list(result.get("files", {}).items())
        if len(files_list) == 0:
            raise ValueError("No matching files found. Check your directory and include/exclude patterns.")
        return files_list

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res  # List of (path, content) tuples


class IdentifyAbstractions(Node):
    def prep(self, shared):
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True
        max_abstraction_num = shared.get("max_abstraction_num", 10)  # Get max_abstraction_num, default to 10
        thinking_level = shared.get("thinking_level", None)

        # Helper to create context from files, respecting limits (basic example)
        def create_llm_context(files_data):
            # Retrieve max tokens limit
            max_tokens = resolve_max_tokens(shared)
            
            safety_limit = int(max_tokens * 0.95)
            
            count_tokens = create_token_counter()

            context = ""
            file_info = []  # Store tuples of (index, path)
            current_tokens = 0
            
            for i, (path, content) in enumerate(files_data):
                entry = f"--- File Index {i}: {path} ---\n{content}\n\n"
                
                entry_tokens = count_tokens(entry)
                
                if current_tokens + entry_tokens > safety_limit:
                    print(f"\033[93mWarning: Context truncated at file index {i} ({path}) to fit within limit of {safety_limit} tokens.\033[0m")
                    break
                    
                context += entry
                file_info.append((i, path))
                current_tokens += entry_tokens

            return context, file_info  # file_info is list of (index, path)

        context, file_info = create_llm_context(files_data)
        # Format file info for the prompt (comment is just a hint for LLM)
        file_listing_for_prompt = "\n".join(
            [f"- {idx} # {path}" for idx, path in file_info]
        )
        return (
            context,
            file_listing_for_prompt,
            len(files_data),
            project_name,
            language,
            use_cache,
            max_abstraction_num,
            thinking_level,
            shared.get("advanced_mode", False),
            shared.get("max_tokens", 100000),
            shared.get("mode", "tutorial"),
        )  # Return all parameters

    def exec(self, prep_res):
        try:
            (
                context,
                file_listing_for_prompt,
                total_files_count,
                project_name,
                language,
                use_cache,
                max_abstraction_num,
                thinking_level,
                advanced_mode,
                max_tokens,
                doc_mode,
            ) = prep_res  # Unpack all parameters
            
            # Add language instruction and hints only if not English
            language_instruction = ""
            name_lang_hint = ""
            desc_lang_hint = ""
            if language.lower() != "english":
                language_instruction = f"IMPORTANT: Generate the `name` and `description` for each abstraction in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
                # Keep specific hints here as name/description are primary targets
                name_lang_hint = f" (value in {language.capitalize()})"
                desc_lang_hint = f" (value in {language.capitalize()})"

            prompt_template = load_prompt_template("identify_abstractions", mode=doc_mode)

            prompt = prompt_template.format(
                project_name=project_name,
                context=context,
                language_instruction=language_instruction,
                max_abstraction_num=max_abstraction_num,
                name_lang_hint=name_lang_hint,
                desc_lang_hint=desc_lang_hint,
                file_listing_for_prompt=file_listing_for_prompt
            )

            log_token_estimation(self.__class__.__name__, prompt, max_tokens)
            print(f"Identifying abstractions using LLM...")
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)  # Use cache only if enabled and not retrying

            # --- Validation ---
            abstractions = parse_yaml_response(response)

            if not isinstance(abstractions, list):
                raise ValueError("LLM Output is not a list")

            validated_abstractions = []
            for item in abstractions:
                if not isinstance(item, dict) or not all(
                    k in item for k in ["name", "description", "file_indices"]
                ):
                    raise ValueError(f"Missing keys in abstraction item: {item}")
                if not isinstance(item["name"], str):
                    raise ValueError(f"Name is not a string in item: {item}")
                if not isinstance(item["description"], str):
                    raise ValueError(f"Description is not a string in item: {item}")
                if not isinstance(item["file_indices"], list):
                    raise ValueError(f"file_indices is not a list in item: {item}")

                # Validate indices
                import re
                validated_indices = []
                for idx_entry in item["file_indices"]:
                    try:
                        idx_str = str(idx_entry).split("#")[0].strip()
                        # Split by '-' to handle ranges
                        if '-' in idx_str:
                            parts = idx_str.split('-')
                            if len(parts) == 2:
                                start_idx = int(re.findall(r'\d+', parts[0])[0])
                                end_idx = int(re.findall(r'\d+', parts[1])[0])
                                for idx in range(start_idx, end_idx + 1):
                                    if 0 <= idx < total_files_count:
                                        validated_indices.append(idx)
                                continue
                        # Find integers in the string
                        nums = re.findall(r'\d+', idx_str)
                        if nums:
                            idx = int(nums[0])
                            if 0 <= idx < total_files_count:
                                validated_indices.append(idx)
                    except (ValueError, TypeError, IndexError):
                        print(f"\033[93mWarning: Could not parse index from entry: {idx_entry} in item {item['name']}\033[0m")
                        continue

                item["files"] = sorted(list(set(validated_indices)))
                # Store only the required fields
                validated_abstractions.append(
                    {
                        "name": item["name"],  # Potentially translated name
                        "description": item[
                            "description"
                        ],  # Potentially translated description
                        "files": item["files"],
                    }
                )

            print(f"Identified {len(validated_abstractions)} abstractions.")
            return validated_abstractions
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res):
        shared["abstractions"] = (
            exec_res  # List of {"name": str, "description": str, "files": [int]}
        )


class AnalyzeRelationships(Node):
    def prep(self, shared):
        abstractions = shared[
            "abstractions"
        ]  # Now contains 'files' list of indices, name/description potentially translated
        files_data = shared["files"]
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True
        thinking_level = shared.get("thinking_level", None)

        # Get the actual number of abstractions directly
        num_abstractions = len(abstractions)

        # Create context with abstraction names, indices, descriptions, and relevant file snippets
        context = "Identified Abstractions:\\n"
        all_relevant_indices = set()
        abstraction_info_for_prompt = []
        for i, abstr in enumerate(abstractions):
            # Use 'files' which contains indices directly
            file_indices_str = ", ".join(map(str, abstr["files"]))
            # Abstraction name and description might be translated already
            info_line = f"- Index {i}: {abstr['name']} (Relevant file indices: [{file_indices_str}])\\n  Description: {abstr['description']}"
            context += info_line + "\\n"
            abstraction_info_for_prompt.append(
                f"{i} # {abstr['name']}"
            )  # Use potentially translated name here too
            all_relevant_indices.update(abstr["files"])

        context += "\\nRelevant File Snippets (per abstraction, budget-aware):\\n"
        # Dynamically include as many files as possible per abstraction.
        # Budget is split EVENLY across abstractions so later ones aren't starved.
        # Unused budget from one abstraction rolls over to the next.
        max_tokens = shared.get("max_tokens", 100000)
        safety_limit = int(max_tokens * 0.95)
        prompt_overhead = 2000  # approximate tokens for prompt template + response

        estimate_tokens = create_token_counter()
        current_tokens = estimate_tokens(context)

        total_budget = safety_limit - current_tokens - prompt_overhead
        num_abstractions = len(abstractions)



        # Pre-compute file token sizes for all abstractions
        abstr_file_data = []  # list of [(idx, path, content, tokens), ...] per abstraction
        for abstr in abstractions:
            sized = []
            for idx in abstr["files"]:
                if 0 <= idx < len(files_data):
                    path, file_content = files_data[idx]
                    entry = f"\\n--- File: {idx} # {path} ---\\n{file_content}\\n"
                    sized.append((idx, path, file_content, estimate_tokens(entry)))
            # Sort largest first (most architecturally significant)
            sized.sort(key=lambda x: x[3], reverse=True)
            abstr_file_data.append(sized)

        # Two-pass allocation:
        # Pass 1: give each abstraction an equal share, track unused
        # Pass 2: redistribute unused budget to abstractions that need more
        per_abstr_budget = total_budget // max(num_abstractions, 1)
        included_indices = set()
        # Track what each abstraction selected and what's left over
        abstr_results = []  # list of (included_files, remaining_files, unused_budget)

        for i, sized in enumerate(abstr_file_data):
            budget = per_abstr_budget
            included_files = []
            remaining_files = []
            for idx, path, file_content, tokens in sized:
                if idx in included_indices:
                    included_files.append((idx, path, None, 0))
                    continue
                if tokens <= budget:
                    included_files.append((idx, path, file_content, tokens))
                    budget -= tokens
                    included_indices.add(idx)
                else:
                    remaining_files.append((idx, path, file_content, tokens))
            abstr_results.append((included_files, remaining_files, budget))

        # Pass 2: redistribute unused budget to abstractions with remaining files
        total_unused = sum(r[2] for r in abstr_results)
        if total_unused > 0:
            for i, (included_files, remaining_files, _unused) in enumerate(abstr_results):
                if not remaining_files or total_unused <= 0:
                    continue
                still_remaining = []
                for idx, path, file_content, tokens in remaining_files:
                    if idx in included_indices:
                        included_files.append((idx, path, None, 0))
                        continue
                    if tokens <= total_unused:
                        included_files.append((idx, path, file_content, tokens))
                        total_unused -= tokens
                        included_indices.add(idx)
                    else:
                        still_remaining.append((idx, path, file_content, tokens))
                abstr_results[i] = (included_files, still_remaining, 0)

        # Build context output
        for i, abstr in enumerate(abstractions):
            included_files, remaining_files, _ = abstr_results[i]
            if included_files or remaining_files:
                context += f"\\n--- Abstraction {i}: {abstr['name']} ---\\n"
                for idx, path, file_content, _tokens in included_files:
                    if file_content is not None:
                        context += f"\\n--- File: {idx} # {path} ---\\n{file_content}\\n"
                    else:
                        context += f"  (File {idx} # {path} -- already shown above)\\n"
                if remaining_files:
                    rest_list = ", ".join(f"{idx} # {p}" for idx, p, _c, _t in remaining_files)
                    context += f"  Other files (path only, budget exhausted): {rest_list}\\n"

        return (
            context,
            "\n".join(abstraction_info_for_prompt),
            num_abstractions, # Pass the actual count
            project_name,
            language,
            use_cache,
            thinking_level,
            shared.get("advanced_mode", False),
            shared.get("max_tokens", 100000),
            shared.get("mode", "tutorial"),
        )  # Return use_cache

    def exec(self, prep_res):
        try:
            (
                context,
                abstraction_listing,
                num_abstractions, # Receive the actual count
                project_name,
                language,
                use_cache,
                thinking_level,
                advanced_mode,
                max_tokens,
                doc_mode,
             ) = prep_res  # Unpack use_cache

            # Add language instruction and hints only if not English
            language_instruction = ""
            lang_hint = ""
            list_lang_note = ""
            if language.lower() != "english":
                language_instruction = f"IMPORTANT: Generate the `summary` and relationship `label` fields in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
                lang_hint = f" (in {language.capitalize()})"
                list_lang_note = f" (Names might be in {language.capitalize()})"  # Note for the input list

            prompt_template = load_prompt_template("identify_relationships", mode=doc_mode)

            prompt = prompt_template.format(
                project_name=project_name,
                list_lang_note=list_lang_note,
                abstraction_listing=abstraction_listing,
                context=context,
                language_instruction=language_instruction,
                lang_hint=lang_hint
            )
            log_token_estimation(self.__class__.__name__, prompt, max_tokens)
            print(f"Analyzing relationships using LLM...")
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying

            # --- Validation ---
            relationships_data = parse_yaml_response(response)

            if not isinstance(relationships_data, dict) or not all(
                k in relationships_data for k in ["summary", "relationships"]
            ):
                raise ValueError(
                    "LLM output is not a dict or missing keys ('summary', 'relationships')"
                )
            if not isinstance(relationships_data["summary"], str):
                raise ValueError("summary is not a string")
            if not isinstance(relationships_data["relationships"], list):
                raise ValueError("relationships is not a list")

            # Validate relationships structure
            import re
            validated_relationships = []
            for rel in relationships_data["relationships"]:
                # Check for 'label' key
                if not isinstance(rel, dict) or not all(
                    k in rel for k in ["from_abstraction", "to_abstraction", "label"]
                ):
                    raise ValueError(
                        f"Missing keys (expected from_abstraction, to_abstraction, label) in relationship item: {rel}"
                    )
                # Validate 'label' is a string
                if not isinstance(rel["label"], str):
                    raise ValueError(f"Relationship label is not a string: {rel}")

                # Validate indices
                try:
                    from_idx_str = str(rel["from_abstraction"]).split("#")[0].strip()
                    to_idx_str = str(rel["to_abstraction"]).split("#")[0].strip()
                    
                    from_nums = re.findall(r'\d+', from_idx_str)
                    to_nums = re.findall(r'\d+', to_idx_str)
                    
                    if not from_nums or not to_nums:
                         raise ValueError("Missing valid integer for from_abstraction or to_abstraction.")

                    from_idx = int(from_nums[0])
                    to_idx = int(to_nums[0])
                    if not (
                        0 <= from_idx < num_abstractions and 0 <= to_idx < num_abstractions
                    ):
                        print(f"\033[93mWarning: Invalid index in relationship: from={from_idx}, to={to_idx}. Max index is {num_abstractions-1}. Skipping.\033[0m")
                        import logging
                        logging.warning(f"Invalid index in relationship: from={from_idx}, to={to_idx}")
                        continue
                    validated_relationships.append(
                        {
                            "from": from_idx,
                            "to": to_idx,
                            "label": rel["label"],  # Potentially translated label
                        }
                    )
                except (ValueError, TypeError, IndexError) as e:
                    print(f"\033[93mWarning: Could not parse indices from relationship: {rel}, error: {e}. Skipping.\033[0m")
                    continue

            print("Generated project summary and relationship details.")
            return {
                "summary": relationships_data["summary"],  # Potentially translated summary
                "details": validated_relationships,  # Store validated, index-based relationships with potentially translated labels
            }
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res):
        # Structure is now {"summary": str, "details": [{"from": int, "to": int, "label": str}]}
        # Summary and label might be translated
        shared["relationships"] = exec_res


class OrderChapters(Node):
    def prep(self, shared):
        abstractions = shared["abstractions"]  # Name/description might be translated
        relationships = shared["relationships"]  # Summary/label might be translated
        project_name = shared["project_name"]  # Get project name
        language = shared.get("language", "english")  # Get language
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True
        thinking_level = shared.get("thinking_level", None)

        # Prepare context for the LLM
        abstraction_info_for_prompt = []
        for i, a in enumerate(abstractions):
            abstraction_info_for_prompt.append(
                f"- {i} # {a['name']}"
            )  # Use potentially translated name
        abstraction_listing = "\n".join(abstraction_info_for_prompt)

        # Use potentially translated summary and labels
        summary_note = ""
        if language.lower() != "english":
            summary_note = (
                f" (Note: Project Summary might be in {language.capitalize()})"
            )

        context = f"Project Summary{summary_note}:\n{relationships['summary']}\n\n"
        context += "Relationships (Indices refer to abstractions above):\n"
        for rel in relationships["details"]:
            from_name = abstractions[rel["from"]]["name"]
            to_name = abstractions[rel["to"]]["name"]
            # Use potentially translated 'label'
            context += f"- From {rel['from']} ({from_name}) to {rel['to']} ({to_name}): {rel['label']}\n"  # Label might be translated

        list_lang_note = ""
        if language.lower() != "english":
            list_lang_note = f" (Names might be in {language.capitalize()})"

        return (
            abstraction_listing,
            context,
            len(abstractions),
            project_name,
            list_lang_note,
            use_cache,
            thinking_level,
            shared.get("advanced_mode", False),
            shared.get("max_tokens", 100000),
            shared.get("mode", "tutorial"),
        )  # Return use_cache

    def exec(self, prep_res):
        try:
            (
                abstraction_listing,
                context,
                num_abstractions,
                project_name,
                list_lang_note,
                use_cache,
                thinking_level,
                advanced_mode,
                max_tokens,
                doc_mode,
            ) = prep_res  # Unpack use_cache
            # No language variation needed here in prompt instructions, just ordering based on structure
            # The input names might be translated, hence the note.

            prompt_template = load_prompt_template("order_chapters", mode=doc_mode)

            prompt = prompt_template.format(
                project_name=project_name,
                list_lang_note=list_lang_note,
                abstraction_listing=abstraction_listing,
                context=context
            )
            log_token_estimation(self.__class__.__name__, prompt, max_tokens)
            print("Determining chapter order using LLM...")
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying

            # --- Validation ---
            ordered_indices_raw = parse_yaml_response(response)

            if not isinstance(ordered_indices_raw, list):
                raise ValueError("LLM output is not a list")

            ordered_indices = []
            seen_indices = set()
            for entry in ordered_indices_raw:
                try:
                    if isinstance(entry, int):
                        idx = entry
                    elif isinstance(entry, str) and "#" in entry:
                        idx = int(entry.split("#")[0].strip())
                    else:
                        idx = int(str(entry).strip())

                    if not (0 <= idx < num_abstractions):
                        raise ValueError(
                            f"Invalid index {idx} in ordered list. Max index is {num_abstractions-1}."
                        )
                    if idx in seen_indices:
                        raise ValueError(f"Duplicate index {idx} found in ordered list.")
                    ordered_indices.append(idx)
                    seen_indices.add(idx)

                except (ValueError, TypeError):
                    raise ValueError(
                        f"Could not parse index from ordered list entry: {entry}"
                    )

            # Check if all abstractions are included
            if len(ordered_indices) != num_abstractions:
                raise ValueError(
                    f"Ordered list length ({len(ordered_indices)}) does not match number of abstractions ({num_abstractions}). Missing indices: {set(range(num_abstractions)) - seen_indices}"
                )

            print(f"Determined chapter order (indices): {ordered_indices}")
            return ordered_indices  # Return the list of indices
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res):
        # exec_res is already the list of ordered indices
        shared["chapter_order"] = exec_res  # List of indices


class WriteChapters(BatchNode):
    def prep(self, shared):
        chapter_order = shared["chapter_order"]  # List of indices
        abstractions = shared[
            "abstractions"
        ]  # List of {"name": str, "description": str, "files": [int]}
        files_data = shared["files"]  # List of (path, content) tuples
        project_name = shared["project_name"]
        language = shared.get("language", "english")
        use_cache = shared.get("use_cache", True)  # Get use_cache flag, default to True
        thinking_level = shared.get("thinking_level", None)

        # Get already written chapters to provide context
        # We store them temporarily during the batch run, not in shared memory yet
        # The 'previous_chapters_summary' will be built progressively in the exec context
        self.chapters_written_so_far = (
            []
        )  # Use instance variable for temporary storage across exec calls

        # Create a complete list of all chapters
        all_chapters = []
        chapter_filenames = {}  # Store chapter filename mapping for linking
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                chapter_num = i + 1
                chapter_name = abstractions[abstraction_index][
                    "name"
                ]  # Potentially translated name
                is_mkdocs = shared.get("mkdocs", False)
                if is_mkdocs and "original_path" in abstractions[abstraction_index]:
                    doc_rel_path = os.path.splitext(abstractions[abstraction_index]["original_path"])[0] + ".md"
                    filename = doc_rel_path.replace(os.sep, "/")
                elif is_mkdocs:
                    safe_name = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
                    filename = f"{safe_name}.md"
                else:
                    safe_name = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
                    filename = f"{i+1:02d}_{safe_name}.md"
                
                # Format with link (using potentially translated name)
                all_chapters.append(f"{chapter_num}. [{chapter_name}]({filename})")
                # Store mapping of chapter index to filename for linking
                chapter_filenames[abstraction_index] = {
                    "num": chapter_num,
                    "name": chapter_name,
                    "filename": filename,
                }

        # Create a formatted string with all chapters
        full_chapter_listing = "\n".join(all_chapters)

        items_to_process = []
        for i, abstraction_index in enumerate(chapter_order):
            if 0 <= abstraction_index < len(abstractions):
                abstraction_details = abstractions[
                    abstraction_index
                ]  # Contains potentially translated name/desc
                # Use 'files' (list of indices) directly
                related_file_indices = abstraction_details.get("files", [])
                # Get content using helper, passing indices
                related_files_content_map = get_content_for_indices(
                    files_data, related_file_indices
                )

                # Get previous chapter info for transitions (uses potentially translated name)
                prev_chapter = None
                if i > 0:
                    prev_idx = chapter_order[i - 1]
                    prev_chapter = chapter_filenames[prev_idx]

                # Get next chapter info for transitions (uses potentially translated name)
                next_chapter = None
                if i < len(chapter_order) - 1:
                    next_idx = chapter_order[i + 1]
                    next_chapter = chapter_filenames[next_idx]

                items_to_process.append(
                    {
                        "chapter_num": i + 1,
                        "abstraction_index": abstraction_index,
                        "abstraction_details": abstraction_details,  # Has potentially translated name/desc
                        "related_files_content_map": related_files_content_map,
                        "project_name": shared["project_name"],  # Add project name
                        "full_chapter_listing": full_chapter_listing,  # Add the full chapter listing (uses potentially translated names)
                        "chapter_filenames": chapter_filenames,  # Add chapter filenames mapping (uses potentially translated names)
                        "prev_chapter": prev_chapter,  # Add previous chapter info (uses potentially translated name)
                        "next_chapter": next_chapter,  # Add next chapter info (uses potentially translated name)
                        "language": language,  # Add language for multi-language support
                        "use_cache": use_cache, # Pass use_cache flag
                        "thinking_level": thinking_level,
                        "advanced_mode": shared.get("advanced_mode", False),
                        "mode": shared.get("mode", "tutorial"),
                        "mkdocs": shared.get("mkdocs", False),
                        "incremental": shared.get("incremental", False),
                        "output_dir": shared.get("output_dir", "output"),
                        "filename": chapter_filenames[abstraction_index]["filename"],
                        "max_tokens": shared.get("max_tokens", 100000),

                        # previous_chapters_summary will be added dynamically in exec
                    }
                )
            else:
                print(
                    f"Warning: Invalid abstraction index {abstraction_index} in chapter_order. Skipping."
                )

        print(f"Preparing to write {len(items_to_process)} chapters...")
        return items_to_process  # Iterable for BatchNode

    def exec(self, item):
        try:
            # This runs for each item prepared above
            abstraction_name = item["abstraction_details"][
                "name"
            ]  # Potentially translated name
            abstraction_description = item["abstraction_details"][
                "description"
            ]  # Potentially translated description
            chapter_num = item["chapter_num"]
            project_name = item.get("project_name")
            language = item.get("language", "english")
            use_cache = item.get("use_cache", True) # Read use_cache from item
            thinking_level = item.get("thinking_level", None)
            advanced_mode = item.get("advanced_mode", False)
            doc_mode = item.get("mode", "tutorial")
            is_mkdocs = item.get("mkdocs", False)
            incremental = item.get("incremental", False)
            output_dir = item.get("output_dir", "output")
            filename = item.get("filename")
            max_tokens = item.get("max_tokens", 100000)

            # Prepare file context string from the map
            file_context_str = "\n\n".join(
                f"--- File: {idx_path.split('# ')[1] if '# ' in idx_path else idx_path} ---\n{content}"
                for idx_path, content in item["related_files_content_map"].items()
            )

            # --- Incremental Caching Logic ---
            current_hash = None
            if incremental and output_dir:
                import hashlib, json
                hasher = hashlib.md5()
                hasher.update(file_context_str.encode("utf-8"))
                current_hash = hasher.hexdigest()
                
                manifest_path = os.path.join(output_dir, project_name, ".doc_cache_manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)
                        if manifest.get(abstraction_name) == current_hash:
                            # Cache hit! Read existing file
                            file_path = os.path.join(output_dir, project_name, "docs", "api", filename) if is_mkdocs else os.path.join(output_dir, project_name, filename)
                            if os.path.exists(file_path):
                                print(f"Incremental Cache Hit: Skipping LLM for {abstraction_name}")
                                with open(file_path, "r", encoding="utf-8") as f:
                                    cached_content = f.read()
                                    
                                # If it's mkdocs, strip the frontmatter before adding to chapters_written_so_far
                                clean_content = cached_content
                                if is_mkdocs and clean_content.startswith("---"):
                                    parts = clean_content.split("---", 2)
                                    if len(parts) >= 3:
                                        clean_content = parts[2].strip()
                                        
                                self.chapters_written_so_far.append(clean_content)
                                return {"content": clean_content, "hash": current_hash, "name": abstraction_name}
                    except Exception as e:
                        print(f"Warning: Failed to read manifest cache: {e}")

            # Get summary of chapters written *before* this one
            # Use the temporary instance variable
            previous_chapters_summary = "\n---\n".join(self.chapters_written_so_far)

            # Add language instruction and context notes only if not English
            language_instruction = ""
            concept_details_note = ""
            structure_note = ""
            prev_summary_note = ""
            instruction_lang_note = ""
            mermaid_lang_note = ""
            code_comment_note = ""
            link_lang_note = ""
            tone_note = ""
            if language.lower() != "english":
                lang_cap = language.capitalize()
                language_instruction = f"IMPORTANT: Write this ENTIRE tutorial chapter in **{lang_cap}**. Some input context (like concept name, description, chapter list, previous summary) might already be in {lang_cap}, but you MUST translate ALL other generated content including explanations, examples, technical terms, and potentially code comments into {lang_cap}. DO NOT use English anywhere except in code syntax, required proper nouns, or when specified. The entire output MUST be in {lang_cap}.\n\n"
                concept_details_note = f" (Note: Provided in {lang_cap})"
                structure_note = f" (Note: Chapter names might be in {lang_cap})"
                prev_summary_note = f" (Note: This summary might be in {lang_cap})"
                instruction_lang_note = f" (in {lang_cap})"
                mermaid_lang_note = f" (Use {lang_cap} for labels/text if appropriate)"
                code_comment_note = f" (PRESERVE original code comments exactly as-is. Add your explanatory notes OUTSIDE code blocks in {lang_cap}, not inside them.)"
                link_lang_note = (
                    f" (Use the {lang_cap} chapter title from the structure above)"
                )
                tone_note = f" (appropriate for {lang_cap} readers)"

            prompt_template = load_prompt_template("draft_chapters", mode=doc_mode)

            prompt = prompt_template.format(
                language_instruction=language_instruction,
                project_name=project_name,
                abstraction_name=abstraction_name,
                chapter_num=chapter_num,
                concept_details_note=concept_details_note,
                abstraction_description=abstraction_description,
                structure_note=structure_note,
                full_chapter_listing=item["full_chapter_listing"],
                prev_summary_note=prev_summary_note,
                previous_chapters_summary=previous_chapters_summary if previous_chapters_summary else "This is the first chapter.",
                file_context_str=file_context_str if file_context_str else "No specific code snippets provided for this abstraction.",
                language=language.capitalize(),
                instruction_lang_note=instruction_lang_note,
                link_lang_note=link_lang_note,
                code_comment_note=code_comment_note,
                mermaid_lang_note=mermaid_lang_note,
                tone_note=tone_note
            )
            log_token_estimation(self.__class__.__name__, prompt, max_tokens)
            print(f"Writing chapter {chapter_num} for: {abstraction_name.strip()} using LLM...")
            chapter_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying
            # Basic validation/cleanup
            actual_heading = f"# Chapter {chapter_num}: {abstraction_name}"  # Use potentially translated name
            if not chapter_content.strip().startswith(f"# Chapter {chapter_num}") and doc_mode != "api-reference":
                # Add heading if missing or incorrect, trying to preserve content
                lines = chapter_content.strip().split("\n")
                if lines and lines[0].strip().startswith(
                    "#"
                ):  # If there's some heading, replace it
                    lines[0] = actual_heading
                    chapter_content = "\n".join(lines)
                else:  # Otherwise, prepend it
                    chapter_content = f"{actual_heading}\n\n{chapter_content}"

            # Add the generated content to our temporary list for the next iteration's context
            self.chapters_written_so_far.append(chapter_content)

            return {"content": chapter_content, "hash": current_hash, "name": abstraction_name}
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res_list):
        import os, json
        # exec_res_list contains dicts with content and hashes
        shared["chapters"] = [res["content"] for res in exec_res_list]
        
        # Save MD5 incremental manifest if enabled
        if shared.get("incremental"):
            output_dir = os.path.join(shared.get("output_dir", "output"), shared.get("project_name"))
            os.makedirs(output_dir, exist_ok=True)
            manifest_path = os.path.join(output_dir, ".doc_cache_manifest.json")
            
            manifest = {}
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception:
                    pass
                    
            for res in exec_res_list:
                if res.get("hash") and res.get("name"):
                    manifest[res["name"]] = res["hash"]
                    
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
                
        # Clean up the temporary instance variable
        del self.chapters_written_so_far
        print(f"Finished writing {len(exec_res_list)} chapters.")


class CombineTutorial(Node):
    def prep(self, shared):
        project_name = shared["project_name"]
        output_base_dir = shared.get("output_dir", "output")  # Default output dir
        output_path = os.path.join(output_base_dir, project_name)
        repo_url = shared.get("repo_url")  # Get the repository URL
        language = shared.get("language", "english")

        # Get potentially translated data
        relationships_data = shared[
            "relationships"
        ]  # {"summary": str, "details": [{"from": int, "to": int, "label": str}]} -> summary/label potentially translated
        chapter_order = shared["chapter_order"]  # indices
        abstractions = shared[
            "abstractions"
        ]  # list of dicts -> name/description potentially translated
        chapters_content = shared[
            "chapters"
        ]  # list of strings -> content potentially translated

        # --- Generate Mermaid Diagram ---
        mermaid_lines = ["flowchart TD"]
        # Add nodes for each abstraction using potentially translated names
        for i, abstr in enumerate(abstractions):
            node_id = f"A{i}"
            # Use potentially translated name, sanitize for Mermaid ID and label
            sanitized_name = abstr["name"].replace('"', "")
            node_label = sanitized_name  # Using sanitized name only
            mermaid_lines.append(
                f'    {node_id}["{node_label}"]'
            )  # Node label uses potentially translated name
        # Add edges for relationships using potentially translated labels
        for rel in relationships_data["details"]:
            from_node_id = f"A{rel['from']}"
            to_node_id = f"A{rel['to']}"
            # Use potentially translated label, sanitize
            edge_label = (
                rel["label"].replace('"', "").replace("\n", " ")
            )  # Basic sanitization
            max_label_len = 30
            if len(edge_label) > max_label_len:
                edge_label = edge_label[: max_label_len - 3] + "..."
            mermaid_lines.append(
                f'    {from_node_id} -- "{edge_label}" --> {to_node_id}'
            )  # Edge label uses potentially translated label

        mermaid_diagram = "\n".join(mermaid_lines)
        # --- End Mermaid ---

        # --- UI string translations for non-English output ---
        ui_strings = {
            "english":    {"tutorial": "Tutorial", "source_repo": "Source Repository", "chapters": "Chapters", "toc": "Table of Contents", "chapter": "Chapter", "full_content": "Full Content"},
            "vietnamese": {"tutorial": "Hướng dẫn", "source_repo": "Kho mã nguồn", "chapters": "Các chương", "toc": "Mục lục", "chapter": "Chương", "full_content": "Nội dung đầy đủ"},
            "chinese":    {"tutorial": "教程", "source_repo": "源代码仓库", "chapters": "章节", "toc": "目录", "chapter": "第", "full_content": "完整内容"},
            "japanese":   {"tutorial": "チュートリアル", "source_repo": "ソースリポジトリ", "chapters": "章", "toc": "目次", "chapter": "章", "full_content": "全文"},
            "korean":     {"tutorial": "튜토리얼", "source_repo": "소스 저장소", "chapters": "챕터", "toc": "목차", "chapter": "챕터", "full_content": "전체 내용"},
            "french":     {"tutorial": "Tutoriel", "source_repo": "Dépôt source", "chapters": "Chapitres", "toc": "Table des matières", "chapter": "Chapitre", "full_content": "Contenu complet"},
            "spanish":    {"tutorial": "Tutorial", "source_repo": "Repositorio fuente", "chapters": "Capítulos", "toc": "Tabla de contenidos", "chapter": "Capítulo", "full_content": "Contenido completo"},
            "german":     {"tutorial": "Anleitung", "source_repo": "Quellrepository", "chapters": "Kapitel", "toc": "Inhaltsverzeichnis", "chapter": "Kapitel", "full_content": "Vollständiger Inhalt"},
            "portuguese": {"tutorial": "Tutorial", "source_repo": "Repositório fonte", "chapters": "Capítulos", "toc": "Índice", "chapter": "Capítulo", "full_content": "Conteúdo completo"},
            "russian":    {"tutorial": "Руководство", "source_repo": "Исходный репозиторий", "chapters": "Главы", "toc": "Оглавление", "chapter": "Глава", "full_content": "Полное содержание"},
            "thai":       {"tutorial": "บทเรียน", "source_repo": "แหล่งโค้ด", "chapters": "บท", "toc": "สารบัญ", "chapter": "บท", "full_content": "เนื้อหาทั้งหมด"},
            "indonesian": {"tutorial": "Tutorial", "source_repo": "Repositori Sumber", "chapters": "Bab", "toc": "Daftar Isi", "chapter": "Bab", "full_content": "Konten Lengkap"},
        }
        ui = ui_strings.get(language.lower(), ui_strings["english"])

        is_mkdocs = shared.get("mkdocs", False)
        
        # --- Prepare index.md or nav_snippet.yml content ---
        if is_mkdocs:
            nav_items = []
            chapter_files = []
            
            for i, abstraction_index in enumerate(chapter_order):
                if 0 <= abstraction_index < len(abstractions) and i < len(chapters_content):
                    abstraction_name = abstractions[abstraction_index]["name"]
                    original_path = abstractions[abstraction_index].get("original_path")
                    
                    if original_path:
                        doc_rel_path = os.path.splitext(original_path)[0] + ".md"
                        filename = doc_rel_path.replace(os.sep, "/")
                    else:
                        safe_name = "".join(c if c.isalnum() else "_" for c in abstraction_name).lower()
                        filename = f"{safe_name}.md"
                    
                    nav_items.append(f"    - '{abstraction_name}': 'api/{filename}'")
                    
                    # Inject YAML Frontmatter
                    chapter_content = chapters_content[i]
                    frontmatter = f"---\ntitle: {abstraction_name}\nsidebar_position: {i + 1}\n---\n\n"
                    
                    if not chapter_content.startswith("---"):
                        chapter_content = frontmatter + chapter_content
                        
                    if not chapter_content.endswith("\n\n"):
                        chapter_content += "\n\n"
                        
                    chapter_files.append({"filename": filename, "content": chapter_content})
                    
            nav_snippet = "nav:\n  - API Reference:\n" + "\n".join(nav_items)
            
            return {
                "output_path": output_path,
                "output_base_dir": output_base_dir,
                "is_mkdocs": True,
                "nav_snippet": nav_snippet,
                "chapter_files": chapter_files,
                "ui": ui,
            }
        else:
            # Traditional tutorial mode
            index_content = f"# {ui['tutorial']}: {project_name}\n\n"
            index_content += f"{relationships_data['summary']}\n\n"
            index_content += f"**{ui['source_repo']}:** [{repo_url}]({repo_url})\n\n"
            
            index_content += "```mermaid\n"
            index_content += mermaid_diagram + "\n"
            index_content += "```\n\n"
            index_content += f"## {ui['chapters']}\n\n"

            chapter_files = []
            for i, abstraction_index in enumerate(chapter_order):
                if 0 <= abstraction_index < len(abstractions) and i < len(chapters_content):
                    abstraction_name = abstractions[abstraction_index]["name"]
                    safe_name = "".join(c if c.isalnum() else "_" for c in abstraction_name).lower()
                    filename = f"{i+1:02d}_{safe_name}.md"
                    index_content += f"{i+1}. [{abstraction_name}]({filename})\n"

                    chapter_content = chapters_content[i]
                    if not chapter_content.endswith("\n\n"):
                        chapter_content += "\n\n"
                    chapter_files.append({"filename": filename, "content": chapter_content})
                else:
                    print(f"Warning: Mismatch between chapter order, abstractions, or content at index {i} (abstraction index {abstraction_index}). Skipping file generation for this entry.")

            index_content += f"\n---\n\n**{ui['full_content']}:** [full_content.md](full_content.md)\n"

            return {
                "output_path": output_path,
                "output_base_dir": output_base_dir,
                "is_mkdocs": False,
                "index_content": index_content,
                "chapter_files": chapter_files,
                "ui": ui,
            }

    def exec(self, prep_res):
        try:
            output_path = prep_res["output_path"]
            output_base_dir = prep_res["output_base_dir"]
            is_mkdocs = prep_res["is_mkdocs"]
            chapter_files = prep_res["chapter_files"]
            ui = prep_res["ui"]

            print(f"Combining tutorial into directory: {output_path}")
            os.makedirs(output_path, exist_ok=True)
            
            if is_mkdocs:
                nav_snippet = prep_res["nav_snippet"]
                api_docs_path = os.path.join(output_path, "docs", "api")
                os.makedirs(api_docs_path, exist_ok=True)
                
                # Write nav_snippet.yml
                nav_filepath = os.path.join(output_path, "docs", "nav_snippet.yml")
                with open(nav_filepath, "w", encoding="utf-8") as f:
                    f.write(nav_snippet)
                print(f"  - Wrote {nav_filepath}")
                
                # Write module API pages
                for chapter_info in chapter_files:
                    chapter_filepath = os.path.join(api_docs_path, chapter_info["filename"])
                    os.makedirs(os.path.dirname(chapter_filepath), exist_ok=True)
                    with open(chapter_filepath, "w", encoding="utf-8") as f:
                        f.write(chapter_info["content"])
                    print(f"  - Wrote {chapter_filepath}")
            else:
                index_content = prep_res["index_content"]
                
                # Write index.md
                index_filepath = os.path.join(output_path, "index.md")
                with open(index_filepath, "w", encoding="utf-8") as f:
                    f.write(index_content)
                print(f"  - Wrote {index_filepath}")

                # Write chapter files
                for chapter_info in chapter_files:
                    chapter_filepath = os.path.join(output_path, chapter_info["filename"])
                    with open(chapter_filepath, "w", encoding="utf-8") as f:
                        f.write(chapter_info["content"])
                    print(f"  - Wrote {chapter_filepath}")
                    
                # Create full_content.md
                toc_lines = [f"# {ui['toc']}\n"]
                full_content_lines = []
                
                for i, chapter_info in enumerate(chapter_files):
                    content = chapter_info["content"]
                    title_line = content.split('\n', 1)[0]
                    if title_line.startswith('# '):
                        title = title_line[2:].strip()
                    else:
                        title = f"{ui['chapter']} {i+1}"
                    
                    toc_lines.append(f"- [{title}](#chapter-{i+1})")
                    full_content_lines.append(f'<a id="chapter-{i+1}"></a>\n')
                    full_content_lines.append(content)
                    full_content_lines.append('\n---\n')
                    
                full_content = "\n".join(toc_lines) + "\n\n" + "\n".join(full_content_lines)
                full_content_filepath = os.path.join(output_path, "full_content.md")
                with open(full_content_filepath, "w", encoding="utf-8") as f:
                    f.write(full_content)
                print(f"  - Wrote {full_content_filepath}")

            return output_path  # Return the final path
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res):
        shared["final_output_dir"] = exec_res  # Store the output path
        print(f"\nGeneration complete! Files are in: {exec_res}")
