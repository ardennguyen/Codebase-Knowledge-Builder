import os
import re
import yaml
import logging
import tiktoken
from pocketflow import Node, BatchNode
from utils.crawl_github_files import crawl_github_files
from utils.call_llm import call_llm, get_model_context_length
from utils.crawl_local_files import crawl_local_files


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
        print(f"Fetched {len(files_list)} files.")
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
            max_tokens = shared.get("max_tokens")
            if max_tokens is None:
                provider = os.environ.get("LLM_PROVIDER")
                if provider == "GEMINI" or not provider:
                    endpoint = "https://generativelanguage.googleapis.com"
                    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
                    api_key = os.getenv("GEMINI_API_KEY", "")
                else:
                    endpoint = os.environ.get(f"{provider}_BASE_URL", "")
                    model_name = os.environ.get(f"{provider}_MODEL", "")
                    api_key = os.environ.get(f"{provider}_API_KEY", "")
                max_tokens = get_model_context_length(endpoint, model_name, api_key)
            
            safety_limit = int(max_tokens * 0.95)
            
            try:
                enc = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                print(f"\033[93mWarning: tiktoken encoding failed: {e}. Falling back to character count estimation.\033[0m")
                enc = None

            context = ""
            file_info = []  # Store tuples of (index, path)
            current_tokens = 0
            
            for i, (path, content) in enumerate(files_data):
                entry = f"--- File Index {i}: {path} ---\n{content}\n\n"
                
                if enc:
                    entry_tokens = len(enc.encode(entry, disallowed_special=()))
                else:
                    # rough fallback estimation: 1 token ~ 4 chars
                    entry_tokens = len(entry) // 4
                
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
        )  # Return all parameters

    def exec(self, prep_res):
        try:
            (
                context,
                file_listing_for_prompt,
                file_count,
                project_name,
                language,
                use_cache,
                max_abstraction_num,
                thinking_level,
                advanced_mode,
            ) = prep_res  # Unpack all parameters
            print(f"Identifying abstractions using LLM...")

            # Add language instruction and hints only if not English
            language_instruction = ""
            name_lang_hint = ""
            desc_lang_hint = ""
            if language.lower() != "english":
                language_instruction = f"IMPORTANT: Generate the `name` and `description` for each abstraction in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
                # Keep specific hints here as name/description are primary targets
                name_lang_hint = f" (value in {language.capitalize()})"
                desc_lang_hint = f" (value in {language.capitalize()})"

            prompt_dir = "advanced" if advanced_mode else "tutorial"
            prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", prompt_dir, "identify_abstractions.md")
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            prompt = prompt_template.format(
                project_name=project_name,
                context=context,
                language_instruction=language_instruction,
                max_abstraction_num=max_abstraction_num,
                name_lang_hint=name_lang_hint,
                desc_lang_hint=desc_lang_hint,
                file_listing_for_prompt=file_listing_for_prompt
            )

            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)  # Use cache only if enabled and not retrying

            # --- Validation ---
            try:
                yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
                abstractions = yaml.safe_load(yaml_str)
            except Exception as e:
                raise ValueError(f"Failed to parse YAML: {e}")

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
                                    if 0 <= idx < file_count:
                                        validated_indices.append(idx)
                                continue
                        # Find integers in the string
                        nums = re.findall(r'\d+', idx_str)
                        if nums:
                            idx = int(nums[0])
                            if 0 <= idx < file_count:
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

        context += "\\nRelevant File Snippets (Referenced by Index and Path):\\n"
        # Get content for relevant files using helper
        relevant_files_content_map = get_content_for_indices(
            files_data, sorted(list(all_relevant_indices))
        )
        # Format file content for context
        file_context_str = "\\n\\n".join(
            f"--- File: {idx_path} ---\\n{content}"
            for idx_path, content in relevant_files_content_map.items()
        )
        context += file_context_str

        return (
            context,
            "\n".join(abstraction_info_for_prompt),
            num_abstractions, # Pass the actual count
            project_name,
            language,
            use_cache,
            thinking_level,
            shared.get("advanced_mode", False),
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
             ) = prep_res  # Unpack use_cache
            print(f"Analyzing relationships using LLM...")

            # Add language instruction and hints only if not English
            language_instruction = ""
            lang_hint = ""
            list_lang_note = ""
            if language.lower() != "english":
                language_instruction = f"IMPORTANT: Generate the `summary` and relationship `label` fields in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n"
                lang_hint = f" (in {language.capitalize()})"
                list_lang_note = f" (Names might be in {language.capitalize()})"  # Note for the input list

            prompt_dir = "advanced" if advanced_mode else "tutorial"
            prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", prompt_dir, "identify_relationships.md")
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            prompt = prompt_template.format(
                project_name=project_name,
                list_lang_note=list_lang_note,
                abstraction_listing=abstraction_listing,
                context=context,
                language_instruction=language_instruction,
                lang_hint=lang_hint
            )
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying

            # --- Validation ---
            try:
                yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
                relationships_data = yaml.safe_load(yaml_str)
            except Exception as e:
                raise ValueError(f"Failed to parse YAML: {e}")

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
            ) = prep_res  # Unpack use_cache
            print("Determining chapter order using LLM...")
            # No language variation needed here in prompt instructions, just ordering based on structure
            # The input names might be translated, hence the note.

            prompt_dir = "advanced" if advanced_mode else "tutorial"
            prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", prompt_dir, "order_chapters.md")
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            prompt = prompt_template.format(
                project_name=project_name,
                list_lang_note=list_lang_note,
                abstraction_listing=abstraction_listing,
                context=context
            )
            response = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying

            # --- Validation ---
            try:
                yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
                ordered_indices_raw = yaml.safe_load(yaml_str)
            except Exception as e:
                raise ValueError(f"Failed to parse YAML: {e}")

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
                # Create safe filename (from potentially translated name)
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in chapter_name
                ).lower()
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
            print(f"Writing chapter {chapter_num} for: {abstraction_name} using LLM...")

            # Prepare file context string from the map
            file_context_str = "\n\n".join(
                f"--- File: {idx_path.split('# ')[1] if '# ' in idx_path else idx_path} ---\n{content}"
                for idx_path, content in item["related_files_content_map"].items()
            )

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
                code_comment_note = f" (Translate to {lang_cap} if possible, otherwise keep minimal English for clarity)"
                link_lang_note = (
                    f" (Use the {lang_cap} chapter title from the structure above)"
                )
                tone_note = f" (appropriate for {lang_cap} readers)"

            prompt_dir = "advanced" if advanced_mode else "tutorial"
            prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", prompt_dir, "draft_chapters.md")
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt_template = f.read()

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
            chapter_content = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level) # Use cache only if enabled and not retrying
            # Basic validation/cleanup
            actual_heading = f"# Chapter {chapter_num}: {abstraction_name}"  # Use potentially translated name
            if not chapter_content.strip().startswith(f"# Chapter {chapter_num}"):
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

            return chapter_content  # Return the Markdown string (potentially translated)
        except Exception as e:
            print(f"\033[93m[Node {self.__class__.__name__} Retry Triggered] Error: {e}\033[0m")
            import logging
            logging.error(f"[Node {self.__class__.__name__}] Error: {e}", exc_info=True)
            raise e

    def post(self, shared, prep_res, exec_res_list):
        # exec_res_list contains the generated Markdown for each chapter, in order
        shared["chapters"] = exec_res_list
        # Clean up the temporary instance variable
        del self.chapters_written_so_far
        print(f"Finished writing {len(exec_res_list)} chapters.")


class CombineTutorial(Node):
    def prep(self, shared):
        project_name = shared["project_name"]
        output_base_dir = shared.get("output_dir", "output")  # Default output dir
        output_path = os.path.join(output_base_dir, project_name)
        repo_url = shared.get("repo_url")  # Get the repository URL
        # language = shared.get("language", "english") # No longer needed for fixed strings

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

        # --- Prepare index.md content ---
        index_content = f"# Tutorial: {project_name}\n\n"
        index_content += f"{relationships_data['summary']}\n\n"  # Use the potentially translated summary directly
        # Keep fixed strings in English
        index_content += f"**Source Repository:** [{repo_url}]({repo_url})\n\n"

        # Add Mermaid diagram for relationships (diagram itself uses potentially translated names/labels)
        index_content += "```mermaid\n"
        index_content += mermaid_diagram + "\n"
        index_content += "```\n\n"

        # Keep fixed strings in English
        index_content += f"## Chapters\n\n"

        chapter_files = []
        # Generate chapter links based on the determined order, using potentially translated names
        for i, abstraction_index in enumerate(chapter_order):
            # Ensure index is valid and we have content for it
            if 0 <= abstraction_index < len(abstractions) and i < len(chapters_content):
                abstraction_name = abstractions[abstraction_index][
                    "name"
                ]  # Potentially translated name
                # Sanitize potentially translated name for filename
                safe_name = "".join(
                    c if c.isalnum() else "_" for c in abstraction_name
                ).lower()
                filename = f"{i+1:02d}_{safe_name}.md"
                index_content += f"{i+1}. [{abstraction_name}]({filename})\n"  # Use potentially translated name in link text

                # Add attribution to chapter content (using English fixed string)
                chapter_content = chapters_content[i]  # Potentially translated content
                if not chapter_content.endswith("\n\n"):
                    chapter_content += "\n\n"

                # Store filename and corresponding content
                chapter_files.append({"filename": filename, "content": chapter_content})
            else:
                print(
                    f"Warning: Mismatch between chapter order, abstractions, or content at index {i} (abstraction index {abstraction_index}). Skipping file generation for this entry."
                )

        return {
            "output_path": output_path,
            "output_base_dir": output_base_dir,
            "index_content": index_content,
            "chapter_files": chapter_files,  # List of {"filename": str, "content": str}
        }

    def exec(self, prep_res):
        try:
            output_path = prep_res["output_path"]
            output_base_dir = prep_res["output_base_dir"]
            index_content = prep_res["index_content"]
            chapter_files = prep_res["chapter_files"]

            print(f"Combining tutorial into directory: {output_path}")
            # Rely on Node's built-in retry/fallback
            os.makedirs(output_path, exist_ok=True)

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
            toc_lines = ["# Table of Contents\n"]
            full_content_lines = []
            
            for i, chapter_info in enumerate(chapter_files):
                content = chapter_info["content"]
                title_line = content.split('\n', 1)[0]
                if title_line.startswith('# '):
                    title = title_line[2:].strip()
                else:
                    title = f"Chapter {i+1}"
                
                toc_lines.append(f"- [{title}](#chapter-{i+1})")
                full_content_lines.append(f'<a id="chapter-{i+1}"></a>\n')
                full_content_lines.append(content)
                full_content_lines.append('\n---\n')
                
            full_content = "\n".join(toc_lines) + "\n\n" + "\n".join(full_content_lines)
            full_content_filepath = os.path.join(output_base_dir, "full_content.md")
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
        print(f"\nTutorial generation complete! Files are in: {exec_res}")
