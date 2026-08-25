---
title: "Architecture & Design"
---

# System Design: Codebase Knowledge Builder

> Please DON'T remove notes for AI

## 1. Requirements

> Notes for AI: Keep it simple and clear.
> If the requirements are abstract, write concrete user stories

**User Story:** As a developer onboarding to a new codebase, I want a tutorial automatically generated from its GitHub repository or local directory, optionally in a specific language. The system supports four documentation styles: a **tutorial mode** that explains core abstractions with beginner-friendly language, analogies, and code walkthroughs; an **advanced mode** that produces architecture deep-dives aimed at senior developers or PMs joining a project mid-way, covering design patterns, key dependencies, and practical onboarding notes; an **api-reference mode** that generates exhaustive, formal API documentation for every code module (1:1 file-to-chapter mapping); and an **sdk mode** that produces SDK-style integration guides. The system must also gracefully handle codebases of any size by dynamically switching to a Map-Reduce approach when context limits are reached.

**Input:**
- A publicly accessible GitHub repository URL or a local directory path.
- A project name (optional, will be derived from the URL/directory if not provided).
- Desired language for the tutorial (optional, defaults to English).
- Advanced configurations: documentation style (`--mode`), token scaling (`--max-tokens`, `--batch`, `--force-batch`), prompting (`--thinking-level`, `--max-abstractions`), caching (`--no-cache`), output format (`--mkdocs`, `--incremental`), debugging (`--debug`), and execution cleanup (`--cleanup`).

**Output:**
- A directory named after the project containing:
    - An `index.md` file with:
        - A high-level project summary (potentially translated).
        - A Mermaid flowchart diagram visualizing relationships between abstractions (using potentially translated names/labels).
        - An ordered list of links to chapter files (using potentially translated names).
        - A link to `full_content.md` at the bottom.
    - Individual Markdown files for each chapter (`01_chapter_one.md`, `02_chapter_two.md`, etc.) detailing core abstractions in a logical order (potentially translated content).
    - A `full_content.md` (inside the project subdirectory) containing all merged chapters and a Table of Contents.
    - When `--mkdocs` is used: YAML frontmatter is injected into every chapter, filenames mirror source directory structure instead of numbered prefixes, and a `nav_snippet.yml` navigation file is generated for MkDocs integration.
    - When `--incremental` is used (api-reference mode only): a `.doc_cache_manifest.json` tracks MD5 hashes of source files to skip regeneration of unchanged modules across runs.

## 2. Flow Design

> Notes for AI:
> 1. Consider the design patterns of agent, map-reduce, rag, and workflow. Apply them if they fit.
> 2. Present a concise, high-level description of the workflow.

### Applicable Design Pattern:

This project primarily uses a **Workflow** pattern with dynamic branching into a **Map-Reduce** pattern. The chapter writing step also utilizes a **BatchNode**.

1.  **Workflow & Routing:** The overall process fetches code, estimates token payloads, and routes based on context limits. If the codebase fits the LLM window, it goes directly to abstraction identification.
2.  **Map-Reduce:** If the codebase exceeds context limits (or if forced), the codebase is grouped into token-aware, directory-isolated batches (each batch stays under the effective token limit and never mixes files from different directories). A `MapAbstractions` BatchNode processes each batch individually, and a `ReduceAbstractions` Node merges them into a global list.
3.  **Batch Processing:** The `WriteChapters` node processes each identified abstraction independently (map) before final tutorial compilation.

### Flow high-level Design:

1.  **`FetchRepo`**: Crawls the specified repository/directory using `crawl_github_files` or `crawl_local_files`.
2.  **`ContextRouter`**: Analyzes the total token payload of the fetched files using `tiktoken`. Dynamically calculates **prompt overhead** (worst-case template tokens across 4 modes × 3 templates + directory tree tokens + chapter listing estimate tokens) and computes an **effective limit** = `safety_limit - prompt_overhead`. If `--mode api-reference` is used, routes to `"deterministic"`. If the file content tokens exceed this effective limit or if `--force-batch` is used, it chunks files into **token-aware, directory-isolated batches** (never mixing files from different directories) and routes to `"batch"`. Also builds a compact directory tree of all files (stored in `shared["directory_tree"]`) for cross-batch awareness. With `--debug`, displays detailed per-batch file lists and token breakdowns. Otherwise, it routes to `"direct"`.
3.  **Path A: Direct**
    *   **`IdentifyAbstractions`**: Analyzes the entire codebase at once to identify core abstractions.
4.  **Path B: Map-Reduce**
    *   **`MapAbstractions` (BatchNode)**: Analyzes each localized directory chunk to extract partial abstractions. Each batch receives the full directory tree for cross-batch awareness.
    *   **`ReduceAbstractions`**: Merges overlapping/partial abstractions into a global list of architecture components.
5.  **Path C: Deterministic** (api-reference mode)
    *   **`DeterministicFileMapper`**: Bypasses LLM-based abstraction discovery entirely. Uses a lightweight LLM call to filter out non-code files (configs, UI layouts, static assets), then creates a 1:1 mapping of each code file to a documentation module. Sorts chapters by **directory depth (deepest first, then alphabetical)** so that utility/leaf files are documented before orchestration files — their summaries become available as cross-chapter context via `previous_chapters_summary`. This ordering is language-agnostic (works for Python, C#, C++, Java, etc.). Skips `AnalyzeRelationships` and `OrderChapters`, routing directly to `WriteChapters`.
6.  **`AnalyzeRelationships`** (Paths A & B only): Takes the unified abstractions list (from either path) and generates a high-level project summary and relationships diagram. Uses token-budget-aware file inclusion: the budget is split evenly across abstractions, with unused budget redistributed in a second pass, maximizing code context without exceeding the context window.
7.  **`OrderChapters`** (Paths A & B only): Determines the most logical sequence to present the abstractions.
8.  **`WriteChapters` (BatchNode)**: Iterates through the ordered abstractions and writes detailed Markdown chapters using context-aware code inclusion.
9.  **`CombineTutorial`**: Assembles the final outputs including `index.md`, individual chapter files, and a compiled `full_content.md`.

```mermaid
flowchart TD
    A[FetchRepo] --> Router[ContextRouter]
    
    Router -->|direct| B[IdentifyAbstractions]
    Router -->|batch| M1[MapAbstractions]
    Router -->|deterministic| DFM[DeterministicFileMapper]
    M1 --> M2[ReduceAbstractions]
    
    B --> C[AnalyzeRelationships]
    M2 --> C
    
    C --> D[OrderChapters]
    D --> E[Batch WriteChapters]
    DFM --> E
    E --> F[CombineTutorial]
```

## 3. Project Structure

> Notes for AI: This is the exact file tree. Create ALL these files when rebuilding.

```
codebase_kb/
├── main.py                          # CLI entry point: parse_arguments, build_shared_store, detect_llm_config, display_config, main orchestrator
├── flow.py                          # PocketFlow graph wiring
├── nodes.py                         # All 10 node classes + helper functions
├── .env.sample                      # Environment variable template
├── requirements.txt                 # Python dependencies
├── .github/
│   └── workflows/
│       └── deploy-docs.yml          # GitHub Actions CI/CD for auto-generating & deploying API docs
├── utils/
│   ├── __init__.py                  # Empty
│   ├── call_llm.py                  # Multi-provider LLM wrapper with caching
│   ├── crawl_github_files.py        # GitHub API crawler
│   ├── crawl_local_files.py         # Local directory crawler
│   ├── exclude_patterns.py          # Centralized definition of DEFAULT_EXCLUDE_PATTERNS
│   ├── output.py                    # Centralized CLI output & logging utility (emit/get/emit_raw)
│   ├── prompts.py                   # Reusable prompt builders for internal LLM calls
│   ├── strings.csv                  # Externalized string table (STRING_KEY, LEVEL, DEST, 12 languages)
│   └── token_utils.py               # Token counting & estimation utilities
├── prompts/
│   ├── tutorial/                    # Beginner-friendly prompt templates
│   │   ├── identify_abstractions.md
│   │   ├── map_abstractions.md
│   │   ├── reduce_abstractions.md
│   │   ├── identify_relationships.md
│   │   ├── order_chapters.md
│   │   └── draft_chapters.md
│   ├── advanced/                    # Senior-dev prompt templates
│   │   ├── identify_abstractions.md
│   │   ├── map_abstractions.md
│   │   ├── reduce_abstractions.md
│   │   ├── identify_relationships.md
│   │   ├── order_chapters.md
│   │   └── draft_chapters.md
│   ├── api-reference/               # Exhaustive API documentation templates
│   │   ├── identify_abstractions.md
│   │   ├── map_abstractions.md
│   │   ├── reduce_abstractions.md
│   │   ├── identify_relationships.md
│   │   ├── order_chapters.md
│   │   └── draft_chapters.md
│   ├── sdk/                         # SDK integration guide templates
│   │   ├── identify_abstractions.md
│   │   ├── map_abstractions.md
│   │   ├── reduce_abstractions.md
│   │   ├── identify_relationships.md
│   │   ├── order_chapters.md
│   │   └── draft_chapters.md
│   └── common/                      # Shared prompts used across modes
│       ├── group_modules.md         # LLM-assisted sidebar nav grouping
│       └── translate_strings.md     # LLM-assisted translation prompt
└── docs/
    ├── design.md                    # THIS FILE
    ├── index.md                     # Project README/landing page
    └── pocketflow/                  # PocketFlow framework reference docs
        ├── guide.md
        ├── index.md
        └── core_abstraction/
            ├── node.md
            ├── flow.md
            ├── communication.md
            ├── batch.md
            ├── async.md
            └── parallel.md
```

## 4. Dependencies

> Notes for AI: Use these EXACT versions in `requirements.txt`.

```
pocketflow>=0.0.3
pyyaml>=6.0.3
requests>=2.34.2
gitpython>=3.1.59
google-cloud-aiplatform>=1.164.0
google-genai>=2.18.1
python-dotenv>=1.2.3
pathspec>=1.1.1
tiktoken>=0.8.0
mkdocs-material>=9.0.0
mkdocs-panzoom-plugin>=0.2.0
```

## 5. Environment Configuration

> Notes for AI: Create `.env.sample` (committed) and `.env` (gitignored). The project uses `python-dotenv` to load `.env`.

### `.env.sample` content:
```ini
# Provider Selection
# LLM_PROVIDER = OPENROUTER

# GitHub Token (Optional, for avoiding rate limits when crawling public repos)
# GITHUB_TOKEN = <YOUR_GITHUB_TOKEN>

# --- Gemini (Default if no LLM_PROVIDER is set) ---
# GEMINI_PROJECT_ID = <YOUR_GEMINI_PROJECT_ID>
# GEMINI_API_KEY = <YOUR_GEMINI_API_KEY>

# --- OpenRouter ---
# OPENROUTER_BASE_URL = https://openrouter.ai/api
# OPENROUTER_API_KEY = <YOUR_OPENROUTER_API_KEY>
# OPENROUTER_MODEL = anthropic/claude-sonnet-4.6
# OPENROUTER_MODEL = google/gemini-3.7-flash
# OPENROUTER_MODEL = qwen/qwen3.8-max

# --- Ollama ---
# OLLAMA_BASE_URL = http://localhost:11434
# OLLAMA_MODEL = llama3
```

### Provider Resolution Logic
```python
provider = os.environ.get("LLM_PROVIDER")
if provider:
    model_name = os.environ.get(f"{provider}_MODEL", "unknown")
    endpoint_url = os.environ.get(f"{provider}_BASE_URL", "unknown")
    api_key = os.environ.get(f"{provider}_API_KEY", "")
else:
    if os.environ.get("GEMINI_PROJECT_ID") or os.environ.get("GEMINI_API_KEY"):
        provider = "GEMINI"
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
        endpoint_url = "generativelanguage.googleapis.com"
        api_key = os.environ.get("GEMINI_API_KEY", "")
    else:
        provider = "UNKNOWN"
        model_name = "unknown"
        endpoint_url = "unknown"
        api_key = ""
```

### Gemini Client Initialization (Vertex AI vs API Key)

> Notes for AI: The Gemini provider supports TWO authentication modes. You MUST implement both.

```python
# In _call_llm_gemini():
if os.getenv("GEMINI_PROJECT_ID"):
    client = genai.Client(
        vertexai=True,
        project=os.getenv("GEMINI_PROJECT_ID"),
        location=os.getenv("GEMINI_LOCATION", "us-central1")
    )
elif os.getenv("GEMINI_API_KEY"):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
else:
    raise ValueError("Either GEMINI_PROJECT_ID or GEMINI_API_KEY must be set")
```

### `.env.sample` Additional Variables
```ini
# Gemini Vertex AI (alternative to API key)
# GEMINI_PROJECT_ID = <YOUR_GCP_PROJECT_ID>
# GEMINI_LOCATION = us-central1
```

## 6. CLI Arguments & Startup Display

> Notes for AI: Implement ALL these CLI arguments in `main.py` via `argparse`. The startup display MUST be printed before the flow runs.

### CLI Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--repo` | `str` | `None` | URL of the public GitHub repository. |
| `--dir` | `str` | `None` | Path to local directory. |
| `-n`, `--name` | `str` | `None` | Project name (optional, derived from repo/directory if omitted). |
| `-t`, `--token` | `str` | `None` | GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided). |
| `-o`, `--output` | `str` | `"output"` | Base directory for output (default: ./output). |
| `-i`, `--include` | `nargs="+"` | `None` | Files to include (e.g., '*.py' '*.js'). Defaults to '*' (all files). |
| `-e`, `--exclude` | `nargs="+"` | `None` | Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native .gitignore rules. |
| `-s`, `--max-size` | `int` | `200000` | Maximum file size in bytes (default: 200000, about 200KB). |
| `--language` | `str` | `"english"` | Language for the generated tutorial (default: english). |
| `--no-cache` | `store_true` | `False` | Disable LLM response caching (default: caching enabled). |
| `--cleanup` | `store_true` | `False` | Clean up logs and cache files. Can be used standalone or after a run. |
| `--max-abstractions` | `int` | `10` | Maximum number of abstractions to identify (default: 10). |
| `--thinking-level` | `str` | `None` | Thinking effort level for native Gemini, OpenRouter, and Ollama reasoning models (e.g., low, medium, high). Leave empty to use model defaults. |
| `--max-tokens` | `int` | `None` | Maximum number of tokens for the context window (default: fetched dynamically). |
| `--mode` | `str` | `"tutorial"` | Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial). |
| `--advanced` | `store_true` | `False` | Legacy flag: equivalent to --mode advanced. |
| `--mkdocs` | `store_true` | `False` | Format output for MkDocs Material (adds YAML frontmatter & nav snippet). |
| `--incremental` | `store_true` | `False` | Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference). |
| `--force-rebuild` | `store_true` | `False` | Clear incremental cache and regenerate all chapters from scratch (use with --incremental). |
| `--batch` | `int` | `50` | Maximum files per batch when using map-reduce mode (default: 50). |
| `--force-batch` | `store_true` | `False` | Force map-reduce mode regardless of context size. |
| `--debug` | `store_true` | `False` | Enable verbose debug output. |

### Startup Config Display
```python
print(f"Starting tutorial generation for: {args.repo or args.dir} in {args.language.capitalize()} language")
print(f"--- Configuration ---")
print(f"AI Provider    : {provider}")
print(f"AI Endpoint    : {endpoint_url}")
print(f"AI Model       : {model_name}")
print(f"Context Length : {context_length:,} tokens")
print(f"Thinking Level : {args.thinking_level if args.thinking_level else 'None'}")
print(f"Advanced Prompts: {'Enabled' if args.advanced else 'Disabled'}")
print(f"Batch Size     : {args.batch} files/batch")
print(f"Force Batch    : {'Enabled' if args.force_batch else 'Disabled'}")
print(f"Max Abstractions: {args.max_abstractions}")
print(f"LLM Caching    : {'Disabled' if args.no_cache else 'Enabled'}")
if args.debug:
    print(f"Debug Mode     : Enabled")
print(f"---------------------")
```

### Argument Validation Rules

These checks run in `main()` after `parse_args()`. All use `emit()` for bilingual output:

| Condition | Severity | Action | String Key |
|---|---|---|---|
| `--advanced` with explicit `--mode` | WARNING | Use advanced, warn user | `WARN_ADVANCED_OVERRIDES_MODE` |
| `--token` without `--repo` | WARNING | Ignore token, warn user | `WARN_TOKEN_NO_REPO` |
| `--force-rebuild` without `--incremental` | ERROR | `sys.exit(1)` | `ERROR_FORCE_REBUILD_NO_INCREMENTAL` |
| `--force-batch` with `--mode api-reference` | WARNING | Clear flag, warn user | `WARN_FORCE_BATCH_API_REF` |
| `--max-abstractions` with `--mode api-reference` | WARNING | Warn user (flag ignored at runtime) | `WARN_MAX_ABS_API_REF` |

Note: `--repo`/`--dir` exclusivity is handled by `argparse.add_mutually_exclusive_group()` (built-in argparse error).

## 7. Default Exclude Patterns

> Notes for AI: This EXACT set must be defined in `utils/exclude_patterns.py` and imported into `main.py` as `DEFAULT_EXCLUDE_PATTERNS`. User-supplied `--exclude` patterns are MERGED with (not replacing) this set via `.union()`.

```python
DEFAULT_INCLUDE_PATTERNS = {"*"}

DEFAULT_EXCLUDE_PATTERNS = {
    # 1. Media, Data, and Static Assets
    "assets/*", "data/*", "images/*", "public/*", "static/*", "temp/*", "tmp/*", "media/*",
    "*.jpg", "*.jpeg", "*.png", "*.gif", "*.ico", "*.svg", "*.webp",
    "*.mp4", "*.webm", "*.mov", "*.mp3", "*.wav",
    "*.pdf", "*.doc", "*.docx", "*.xls", "*.xlsx", "*.ppt", "*.pptx",
    "*.zip", "*.tar", "*.gz", "*.rar", "*.7z",

    # 2. Build, Distribution, and Framework Caches
    "dist/*", "build/*", "out/*", "output/*", "output-test*/*", "target/*", "bin/*", "obj/*",
    ".next/*", ".nuxt/*", ".svelte-kit/*", ".expo/*",
    "docs/*", "test/*", "tests/*", "examples/*",
    "v1/*", "experimental/*", "deprecated/*", "misc/*", "legacy/*",
    "*.log", "*.bak", "*.tmp", "*.swp",

    # 3. Environments, Dependencies & Lockfiles
    "venv/*", ".venv/*", "env/*", ".env", ".env.*",
    "node_modules/*", "bower_components/*", "jspm_packages/*",
    "vendor/*", "packages/*",
    "*.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "Gemfile.lock", "poetry.lock", "mix.lock", "Pipfile.lock",

    # 4. Language-Specific Exclusions
    "__pycache__/*", "*.pyc", "*.pyo", "*.pyd", ".pytest_cache/*", ".ruff_cache/*", ".tox/*", ".coverage", "htmlcov/*", # Python
    ".gradle/*", "*.class", "*.jar", "*.war", "*.ear", "*.nar", # Java / JVM
    "*.o", "*.obj", "*.dll", "*.exe", "*.so", "*.dylib", "*.lib", "*.a", # C/C++/Native
    "ios/Pods/*", "android/.gradle/*", "android/app/build/*", # Mobile

    # 5. OS & Version Control
    ".git/*", ".github/*", ".svn/*", ".hg/*",
    ".DS_Store", "Thumbs.db", "desktop.ini",

    # 6. Classic IDEs
    ".vscode/*", ".idea/*", "*.iml", ".eclipse/*", ".settings/*", ".classpath", ".project", ".vs/*",

    # 7. AI Agents & Modern AI IDEs
    ".cursor/*", ".cursorrules",
    ".windsurf/*", ".windsurfrules",
    ".cline/*", ".clinerules",
    ".roo/*", ".roorules",
    ".agent/*", ".agents/*",
    ".continue/*", ".aide/*",
    ".gemini/*", ".antigravity/*",
    ".claude/*", ".copilot/*",
}
```

## 8. Shared Store Schema

> Notes for AI: This is the EXACT shared store structure. Pay attention to data type transformations noted with ⚠.

```python
shared = {
    # --- Set by main.py from CLI args ---
    "repo_url": args.repo,                    # str | None
    "local_dir": args.dir,                    # str | None
    "project_name": args.name,                # str | None (FetchRepo derives if None)
    "github_token": github_token,             # str | None
    "output_dir": args.output,                # str, default "output"
    "include_patterns": include_set,          # set[str]
    "exclude_patterns": exclude_set,          # set[str]
    "max_file_size": args.max_size,           # int, default 200000
    "language": args.language,                 # str, default "english"
    "use_cache": not args.no_cache,           # bool, default True
    "max_abstraction_num": args.max_abstractions,  # int, default 10
    "thinking_level": args.thinking_level,    # str | None
    "max_tokens": args.max_tokens,            # int | None (auto-detected later)
    "mode": mode,                             # str: "tutorial", "advanced", "api-reference", or "sdk"
    "mkdocs": args.mkdocs,                    # bool, default False
    "incremental": args.incremental,          # bool, default False
    "advanced_mode": mode == "advanced",  # bool, derived from mode
    "batch_size": args.batch,                 # int, default 50
    "force_batch": args.force_batch,          # bool, default False
    "debug": args.debug,                      # bool, default False

    # --- Populated by downstream nodes (NOT initialized in main.py — set at runtime) ---
    "files": [],              # Set by FetchRepo: list[tuple[str, str]] = [(relpath, content), ...]
    "mapped_abstractions": [],# Set by MapAbstractions (batch path only): list[dict]
    "file_batches": [],       # Set by ContextRouter (batch path only): list[list[tuple[int, str, str]]]
    "directory_tree": "",     # Set by ContextRouter (batch path only): str
    "abstractions": [],       # Set by IdentifyAbstractions OR ReduceAbstractions
    "relationships": {},      # Set by AnalyzeRelationships
    "chapter_order": [],      # Set by OrderChapters
    "chapters": [],           # Set by WriteChapters
    "chapter_summaries": [],  # Set by WriteChapters.post(): list[str] — used by CombineTutorial for LLM nav grouping
    "final_output_dir": None  # Set by CombineTutorial
}
```

### Data Transformations Between Nodes

> Notes for AI: These transformations are CRITICAL. An AI builder MUST understand how data shapes change as it flows through nodes.

| Stage | `shared["files"]` format | Who transforms |
|---|---|---|
| After FetchRepo | `[(relpath, content), ...]` — 2-tuples sorted by path | FetchRepo.post |
| Used by ContextRouter | Same 2-tuples — ContextRouter reads but does NOT modify `shared["files"]` | — |
| `shared["file_batches"]` | `[[(global_idx, path, content), ...], ...]` — list of batches, each batch is list of 3-tuples with global index | ContextRouter.post |

| Stage | `shared["abstractions"]` format |
|---|---|
| After Identify/Reduce | `[{"name": str, "description": str, "files": [int, ...]}, ...]` |
| After DeterministicFileMapper | `[{"name": str, "description": str, "files": [int], "original_path": str}, ...]` |
| Note | `"files"` key contains validated integer indices into `shared["files"]`. In api-reference mode, `"original_path"` stores the relative repository path of the source file. |

| Stage | `shared["relationships"]` format |
|---|---|
| After AnalyzeRelationships | `{"summary": str, "details": [{"from": int, "to": int, "label": str}, ...]}` |
| Note | LLM returns `from_abstraction`/`to_abstraction` strings; node parses to int `from`/`to` |

| Stage | `shared["mapped_abstractions"]` format |
|---|---|
| After MapAbstractions | `[{"name": str, "description": str, "files": [int, ...]}, ...]` — flattened from all batches |
| Note | Only exists in batch path. Fed into ReduceAbstractions for merging/deduplication |

| Stage | `shared["directory_tree"]` format |
|---|---|
| After ContextRouter | String built by `build_directory_tree()` — see Section 10 for format |
| Note | Used by IdentifyAbstractions (all modes), MapAbstractions (batch path), and CombineTutorial (nav grouping) for project structure context |

## 9. Utility Interface Contracts

> Notes for AI: These are EXACT function signatures. Do NOT rename parameters. Do NOT change return formats.

### `crawl_local_files`
```python
def crawl_local_files(directory, include_patterns=None, exclude_patterns=None,
                      max_file_size=None, use_relative_paths=True) -> dict:
    # Returns: {"files": {relative_path_str: content_str, ...}}
```

**Directory Pruning Algorithm** (critical for nested directories like `Core.User/.vs/`):
> Note: `DEFAULT_EXCLUDE_PATTERNS` is imported from `utils/exclude_patterns.py`. Nested `.gitignore` files are supported: during `os.walk`, each subdirectory is checked for its own `.gitignore`, and a dict of `{abs_dir_path: pathspec}` is maintained. Matching uses `os.path.relpath()` from each spec's directory.

```python
# During os.walk, for each subdirectory d:
excluded_dirs = set()
for d in dirs:
    abs_d = os.path.join(root, d)
    dirpath_rel = os.path.relpath(abs_d, directory)
    # Check .gitignore first (iterating through nested specs)
    is_ignored = False
    for spec_dir, spec in gitignore_specs.items():
        if abs_d.startswith(spec_dir):
            rel_to_spec = os.path.relpath(abs_d, spec_dir)
            if spec.match_file(rel_to_spec):
                is_ignored = True
                break
    if is_ignored:
        excluded_dirs.add(d)
        continue
    # Check exclude patterns — strip trailing /* for directory matching
    if exclude_patterns:
        for pattern in exclude_patterns:
            dir_pattern = pattern[:-2] if pattern.endswith("/*") else pattern
            if fnmatch.fnmatch(dirpath_rel, dir_pattern) or fnmatch.fnmatch(d, dir_pattern):
                excluded_dirs.add(d)
                break
# Remove matched dirs to prevent os.walk descent
for d in dirs.copy():
    if d in excluded_dirs:
        dirs.remove(d)
```

> Note: Directory validation: raises `ValueError` if `directory` path doesn't exist. Loads `.gitignore` with `utf-8-sig` encoding (BOM-safe). All directories and files are `sorted()` for deterministic traversal order.

**Progress Display Format:**
Output is handled by `utils.output.emit()` using string keys (e.g., `CRAWL_FILE_PROCESSED`).
Colors (Green for processed, Gray for excluded, Red for errors) are configured via the `LEVEL` column in `strings.csv`.

> Note: After crawling, prints a `--- Crawl Summary ---` block with total found, processed, excluded, size limited, and non-text counts.

### `crawl_github_files`
```python
def crawl_github_files(repo_url, token=None, max_file_size=1048576,
                       use_relative_paths=False, include_patterns=None,
                       exclude_patterns=None) -> dict:
    # Returns: {"files": {path_str: content_str, ...}, "stats": {...}}
```

> Notes for AI: This is the most complex utility (~550 lines). You MUST implement ALL subsystems below.

**Imports required:** `requests`, `base64`, `os`, `tempfile`, `git`, `time`, `fnmatch`, `pathspec`, `urlparse`

**Input normalization:** Convert single string patterns to `set`:
```python
if include_patterns and isinstance(include_patterns, str):
    include_patterns = {include_patterns}
if exclude_patterns and isinstance(exclude_patterns, str):
    exclude_patterns = {exclude_patterns}
```

**`should_include_file(file_path, file_name, gitignore_spec=None)` helper:**
- If `include_patterns` set: file must match at least one pattern via `fnmatch.fnmatch(file_name, pattern)`
- If `gitignore_spec`: reject if `gitignore_spec.match_file(file_path)`
- If `exclude_patterns`: reject if `fnmatch.fnmatch(file_path, pattern)` matches any

#### Path 1: SSH/Git Clone
Triggered when `repo_url.startswith("git@") or repo_url.endswith(".git")`:
```python
with tempfile.TemporaryDirectory() as tmpdirname:
    print(f"Cloning SSH repo {repo_url} to temp dir {tmpdirname} ...")
    try:
        repo = git.Repo.clone_from(repo_url, tmpdirname)
    except Exception as e:
        print(f"Error cloning repo: {e}")
        return {"files": {}, "stats": {"error": str(e)}}

    files = {}
    skipped_files = []
    
    # Note for AI: ANSI color constants (C_GREEN, C_GRAY, C_RED, C_RESET) 
    # are no longer needed. Use utils.output.emit() instead.

    # --- Counters ---
    count_processed = 0
    count_excluded = 0
    count_size_limit = 0
    count_non_text = 0
    skipped_size_list = []
    skipped_non_text_list = []
    entry_num = 0

    # --- Load .gitignore (BOM-safe) ---
    gitignore_path = os.path.join(tmpdirname, ".gitignore")
    gitignore_spec = None
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding="utf-8-sig") as f:
                gitignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", f.readlines())
        except Exception:
            pass

    for root, dirs, filenames in os.walk(tmpdirname):
        # --- Directory pruning (same algorithm as crawl_local_files) ---
        excluded_dirs = set()
        for d in sorted(dirs):
            dirpath_rel = os.path.relpath(os.path.join(root, d), tmpdirname)
            reason = None
            if gitignore_spec and gitignore_spec.match_file(dirpath_rel):
                reason = "excluded (.gitignore)"
            elif exclude_patterns:
                for pattern in exclude_patterns:
                    dir_pattern = pattern[:-2] if pattern.endswith("/*") else pattern
                    if fnmatch.fnmatch(dirpath_rel, dir_pattern) or fnmatch.fnmatch(d, dir_pattern):
                        reason = "excluded"
                        break
            if reason:
                excluded_dirs.add(d)
                entry_num += 1
                count_excluded += 1
                print(f"{C_GRAY}  [{entry_num}] {dirpath_rel}/ [{reason}]{C_RESET}")

        for d in dirs.copy():
            if d in excluded_dirs:
                dirs.remove(d)
        dirs.sort()  # Deterministic traversal order

        # --- File processing ---
        for filename in sorted(filenames):
            abs_path = os.path.join(root, filename)
            rel_path = os.path.relpath(abs_path, tmpdirname)
            entry_num += 1

            if not should_include_file(rel_path, filename, gitignore_spec=gitignore_spec):
                count_excluded += 1
                print(f"{C_GRAY}  [{entry_num}] {rel_path} [excluded]{C_RESET}")
                continue

            try:
                file_size = os.path.getsize(abs_path)
            except OSError:
                continue

            if file_size > max_file_size:
                count_size_limit += 1
                skipped_size_list.append(rel_path)
                size_kb = file_size / 1024
                print(f"{C_RED}  [{entry_num}] {rel_path} [size limit: {size_kb:.0f}KB]{C_RESET}")
                continue

            try:
                with open(abs_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                files[rel_path] = content
                count_processed += 1
                print(f"{C_GREEN}  [{entry_num}] {rel_path} [processed]{C_RESET}")
            except (UnicodeDecodeError, ValueError):
                count_non_text += 1
                skipped_non_text_list.append(rel_path)
                print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: not a text file]{C_RESET}")
            except Exception as e:
                count_non_text += 1
                skipped_non_text_list.append(rel_path)
                print(f"{C_RED}  [{entry_num}] {rel_path} [cannot process: {e}]{C_RESET}")

    # --- Crawl Summary ---
    total_fetched = count_processed + count_excluded + count_size_limit + count_non_text
    print(f"\n--- Crawl Summary ---")
    print(f"  Total found : {total_fetched}")
    print(f"{C_GREEN}  Processed   : {count_processed}{C_RESET}")
    if count_excluded > 0:
        print(f"{C_GRAY}  Excluded    : {count_excluded}{C_RESET}")
    if count_size_limit > 0:
        print(f"{C_RED}  Size limit  : {count_size_limit}{C_RESET}")
        for sf in skipped_size_list:
            print(f"{C_RED}    - {sf}{C_RESET}")
    if count_non_text > 0:
        print(f"{C_RED}  Non-text    : {count_non_text}{C_RESET}")
        for sf in skipped_non_text_list:
            print(f"{C_RED}    - {sf}{C_RESET}")
    print(f"---------------------")

    return {
        "files": files,
        "stats": {
            "downloaded_count": len(files),
            "skipped_count": len(skipped_files),
            "skipped_files": skipped_files,
            "base_path": None,
            "include_patterns": include_patterns,
            "exclude_patterns": exclude_patterns,
            "source": "ssh_clone"
        }
    }
```

#### Path 2: GitHub API Crawl

**Step 1 — URL Parsing and Branch/Ref Resolution:**
```python
parsed_url = urlparse(repo_url)
path_parts = parsed_url.path.strip('/').split('/')
owner, repo = path_parts[0], path_parts[1]

headers = {"Accept": "application/vnd.github.v3+json"}
if token:
    headers["Authorization"] = f"token {token}"
```

**Step 2 — Dynamic Branch Detection (handles multi-segment branch names like `feature/foo`):**
```python
if len(path_parts) > 2 and 'tree' == path_parts[2]:
    join_parts = lambda i: '/'.join(path_parts[i:])
    
    # Fetch all branches
    branches = fetch_branches(owner, repo)  # GET /repos/{owner}/{repo}/branches
    branch_names = map(lambda b: b.get("name"), branches)
    
    # Match URL path against branch names (handles multi-segment names)
    relevant_path = join_parts(3)
    ref = next((name for name in branch_names if relevant_path.startswith(name)), None)
    
    # Fallback: check if it's a commit/tree hash
    if ref is None:
        tree = path_parts[3]
        ref = tree if check_tree(owner, repo, tree) else None  # GET /repos/{owner}/{repo}/git/trees/{tree}
    
    # Extract subdirectory (accounts for multi-slash branch names)
    part_index = 5 if '/' in ref else 4
    specific_path = join_parts(part_index) if part_index < len(path_parts) else ""
else:
    ref = None  # Let GitHub use default branch
    specific_path = ""
```

**Step 3 — Remote `.gitignore` Fetch:**
```python
gi_url = f"https://api.github.com/repos/{owner}/{repo}/contents/.gitignore"
gi_params = {"ref": ref} if ref is not None else {}
gi_resp = requests.get(gi_url, headers=headers, params=gi_params, timeout=(10, 10))
if gi_resp.status_code == 200:
    gi_data = gi_resp.json()
    if "content" in gi_data and gi_data.get("encoding") == "base64":
        gi_content = base64.b64decode(gi_data["content"]).decode('utf-8')
        gitignore_spec = pathspec.PathSpec.from_lines("gitwildmatch", gi_content.splitlines())
```

**Step 4 — Recursive Content Fetching (1 API call per directory):**
```python
def fetch_contents(path):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": ref} if ref is not None else {}
    response = requests.get(url, headers=headers, params=params, timeout=(30, 30))
    
    # Rate limit handling with header-based wait:
    if response.status_code in (403, 429) and 'rate limit exceeded' in response.text.lower():
        if not token:
            raise Exception("GitHub API rate limit exceeded. Provide a token.")
        reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
        wait_time = max(reset_time - time.time(), 0) + 1
        time.sleep(wait_time)
        return fetch_contents(path)  # Recursive retry
    
    contents = response.json()
    if not isinstance(contents, list):
        contents = [contents]
    
    for item in contents:
        if item["type"] == "file":
            # Check patterns, size, then fetch content
            # Path A: Use download_url directly, check Content-Length header
            # Path B (fallback): If no download_url, GET item["url"],
            #   base64 decode with size estimate: len(content) * 0.75 > max_file_size
        elif item["type"] == "dir":
            # Check gitignore + exclude before recursing
            fetch_contents(item["path"])
```

**Step 5 — Dual Content Fetch Strategy:**
```python
# Path A: download_url available
if "download_url" in item and item["download_url"]:
    file_response = requests.get(item["download_url"], headers=headers, timeout=(30, 30))
    content_length = int(file_response.headers.get('content-length', 0))
    if content_length > max_file_size:  # Final size check
        continue
    files[rel_path] = file_response.text

# Path B: base64 fallback
else:
    content_response = requests.get(item["url"], headers=headers, timeout=(30, 30))
    content_data = content_response.json()
    if len(content_data["content"]) * 0.75 > max_file_size:  # Approximate size
        continue
    file_content = base64.b64decode(content_data["content"]).decode('utf-8')
    files[rel_path] = file_content
```

**Error Messages (5 scenarios):**
| Status | Condition | Message |
|---|---|---|
| 404 | No token | `"Repository not found or is private. Provide a GitHub token."` |
| 404 | Token, no path, ref='main' | `"Repository not found. Check if default branch is not 'main'"` |
| 404 | Token, with path | `"Path '{path}' not found or insufficient permissions."` |
| 403/429 | No token | Raise exception: `"Rate limit exceeded. Provide a token."` |
| 403/429 | With token | Sleep using `X-RateLimit-Reset` header, recursive retry |

**Stats Return Structure:**
```python
return {
    "files": files,  # {path: content, ...}
    "stats": {
        "downloaded_count": len(files),
        "skipped_count": len(skipped_files),
        "skipped_files": skipped_files,
        "base_path": specific_path if use_relative_paths else None,
        "include_patterns": include_patterns,
        "exclude_patterns": exclude_patterns,
        "source": "ssh_clone"  # Only in SSH mode
    }
}
```

> Note: Progress display output is handled by `utils.output.emit()`. Colors (Green for processed, Gray for excluded, Red for errors) are configured via the `LEVEL` column in `strings.csv`. Each line prefixed with entry counter `[{entry_num}]`. End-of-crawl summary block with counts per category.

### `call_llm`
```python
def call_llm(prompt, use_cache=True, thinking_level=None) -> str:
    # Returns: LLM response content as string
```

> Notes for AI: This function has multiple critical subsystems. Implement ALL of them.

**Disk Caching:**
- Cache file: `llm_cache.json`, key = exact prompt string
- Load cache before checking; if hit, return cached response
- Before writing to cache, re-load from disk to prevent concurrent overwrites:
```python
if use_cache:
    cache = load_cache()  # Re-load to avoid overwrites
    cache[prompt] = response_text
    save_cache(cache)
```

**Provider Routing:**
- `get_llm_provider()` reads `LLM_PROVIDER` env var; falls back to `"GEMINI"` if `GEMINI_PROJECT_ID` or `GEMINI_API_KEY` exists
- `provider == "GEMINI"` → calls `_call_llm_gemini()`
- Otherwise → calls `_call_llm_provider()` (generic OpenAI-compatible)

**`_call_llm_gemini(prompt, thinking_level=None)` — Gemini-specific:**
```python
# Authentication — MUST support both modes:
if os.getenv("GEMINI_PROJECT_ID"):
    client = genai.Client(vertexai=True, project=os.getenv("GEMINI_PROJECT_ID"),
                          location=os.getenv("GEMINI_LOCATION", "us-central1"))
elif os.getenv("GEMINI_API_KEY"):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Thinking budget mapping:
budget_map = {"low": 1024, "medium": 4096, "high": 8192}
if thinking_level:
    thinking_config = types.ThinkingConfig(include_thoughts=True,
                                           thinking_budget=budget_map.get(thinking_level.lower(), 4096))
    kwargs["config"] = types.GenerateContentConfig(thinking_config=thinking_config)

# CRITICAL — Thought part filtering (avoids 'thought_signature' warnings):
if response.candidates and response.candidates[0].content.parts:
    text_parts = [part.text for part in response.candidates[0].content.parts if part.text is not None]
    return "".join(text_parts)
return ""
```

**`_call_llm_provider(prompt, thinking_level=None)` — OpenAI-compatible REST:**
- URL: `{base_url}/v1/chat/completions`, timeout `(10, 300)`
- Dynamic env var resolution: `{provider}_MODEL`, `{provider}_BASE_URL`, `{provider}_API_KEY`
- Default temperature: `0.7`

**OpenRouter Reasoning Detection:**
```python
if provider == "OPENROUTER" and thinking_level:
    model_info = _get_openrouter_model_info(model)  # Queries /api/v1/models, cached
    if model_info and "reasoning" in model_info:
        supported_efforts = model_info["reasoning"].get("supported_efforts", [])
        if thinking_level.lower() in supported_efforts:
            payload["reasoning"] = {"effort": thinking_level.lower()}
            payload["temperature"] = 1.0  # MUST override to 1.0 when reasoning enabled
```

**Ollama Think Mode:**
```python
elif provider == "OLLAMA" and thinking_level:
    payload["think"] = thinking_level.lower()
    payload["reasoning_effort"] = thinking_level.lower()
    payload["temperature"] = 1.0  # MUST override to 1.0
```

**Logging:** Note that `configure_logging()` has been moved to `utils/output.py`. `call_llm` now relies on `utils.output.emit()` for all output and logging rather than managing its own logger.

### `get_model_context_length`
```python
def get_model_context_length(endpoint_url, model_name, api_key) -> int:
    # Returns 1,000,000 for Gemini models
    # Queries OpenRouter /api/v1/models for OpenRouter models
    # Default fallback: 100,000
```

### `count_tokens`
```python
def count_tokens(text: str) -> int:
    # Returns token count using lazy-loaded tiktoken singleton
    # Fallback: len(text) // 4 if tiktoken unavailable
```
- Uses `tiktoken.get_encoding('cl100k_base')` via module-level singleton (`_get_encoding()`)
- Returns 0 for empty/None text
- Shared by `log_token_estimation`, `call_llm` (prompt_tokens), and `WriteChapters` (breakdown + response counting)

### `log_token_estimation`
```python
def log_token_estimation(node_name: str, prompt_content: str, max_tokens: int,
                         token_usage: dict = None) -> None:
    # Uses emit("TOKEN_ANALYTICS", ...) for stdout and keeps logger.info() for the structured log entry.
```
- Uses `count_tokens()` internally for consistent measurement
- `token_usage` dict: optional per-component token counts. Each key is a label (e.g. `file_context`, `prev_chapters`), value is token count. Displayed as `| label=N (X%)` appended to both CLI and log output.
- **Takes 3-4 arguments** — node_name for display, prompt for counting, max_tokens for percentage, optional token_usage for diagnostics

### `utils/prompts.py` — Reusable Prompt Builders

Internal prompt builders for LLM calls that don't use `prompts/{mode}/` template files.

#### `build_code_file_filter_prompt`
```python
def build_code_file_filter_prompt(project_name: str, file_listing: str) -> str:
```
- Used by `DeterministicFileMapper` in api-reference mode
- Asks LLM to identify which files are actual code (APIs, classes, business logic)
- Excludes: UI layouts (.xaml, .html), configs (.json, .xml), assets, build scripts
- Returns YAML list of file indices

#### `build_chapter_summary_prompt`
```python
def build_chapter_summary_prompt(chapter_num: int, abstraction_name: str,
                                  chapter_content: str, language: str = "english") -> str:
```
- Used by `WriteChapters` after each chapter is generated
- Generates structured technical brief with 4 dimensions (3-5 sentences each):
  1. Component scope & responsibility
  2. Key technical elements (classes, services, functions)
  3. Implementation patterns & architecture
  4. System integration & dependencies
- Language-aware: prefixes with `"Write the entire summary in {language}."` for non-English
- Summary output stored in `self.chapter_summaries[]` for cross-chapter context

#### `build_mkdocs_config`
```python
def build_mkdocs_config(site_name: str, nav_yaml: str) -> str:
```
- Used by `CombineTutorial` in `--mkdocs` mode to generate a ready-to-use `mkdocs.yml`
- Includes Material theme, code copy, syntax highlighting, and mermaid diagram support
- Merges the generated `nav_snippet` into the config's nav section
- Output file can be used directly with `mkdocs serve` or `mkdocs build`

#### `build_mermaid_init_js`
```python
def build_mermaid_init_js() -> str:
```
- Returns JavaScript that initializes Mermaid on `.mermaid-raw` elements (bypasses Material theme overrides)
- **Code unwrapping:** `pymdownx.superfences` `fence_code_format` wraps content as `<pre class="mermaid-raw"><code>...</code></pre>`. The JS unwraps the `<code>` child (moves `textContent` up to `<pre>`) before calling `mermaid.run()`, since Mermaid expects diagram text directly in the target element.
- Uses `securityLevel: 'loose'` and wraps `mermaid.run()` in try-catch with `.catch()` for resilient rendering
- Uses `document.readyState` check instead of bare `DOMContentLoaded` listener for reliable initialization
- Diagrams render with Mermaid's native default theme (yellow subgraph backgrounds, lavender nodes) matching GitHub rendering
- Written to `docs/javascripts/mermaid-init.js` by `CombineTutorial`
- **Must be kept in sync** with `.github/ci_mkdocs_config.py` `MERMAID_INIT_JS` constant

#### `build_grouped_nav`
```python
def build_grouped_nav(sections: list, chapter_files: list, indent: int = 4) -> list[str]:
```
- Recursively builds MkDocs nav YAML lines from LLM-generated section grouping
- Handles arbitrary nesting via `children` key in sections
- Each module is matched to `chapter_files` by `module_name`. Each `chapter_files` entry must include `original_path` for directory sub-grouping.
- Files in subdirectories are **always** auto-sub-grouped by their full directory path (deterministic, no extra LLM call). Root-level files remain flat (no sub-layer). Module names inside dir sub-layers are bare (no directory prefix).
- Returns list of indented YAML lines

#### `collect_all_modules`
```python
def collect_all_modules(sections: list) -> set:
```
- Recursively collects all module names from a sections tree
- Used to validate LLM grouping covers all modules (ungrouped → "Other" section)

#### `CombineTutorial._build_index_sections` (static method in `nodes.py`)
```python
@staticmethod
def _build_index_sections(lines: list, sections: list, chapter_files: list, level: int = 3):
```
- Recursively builds markdown sections with module tables for `api/index.md`
- Each section gets a heading (`###`, `####`, etc.) and a `| Chapter | Description |` table
- **Bare module names:** Chapter column displays bare `mod_name` (e.g., `[call_llm.py](...)`) — directory context is provided by the section heading, not the filename
- **Smart description extraction:** When `description` starts with `"Internal API reference"` (the generic DeterministicFileMapper description), extracts the first meaningful paragraph from chapter content instead (skipping frontmatter, headings, code fences)
- **Link paths:** Uses `match['filename']` directly (e.g., `utils/call_llm.py.md`) — NOT prefixed with `api/` since `index.md` is already at `docs/api/index.md`

#### Dynamic Nav Section Labels

`CombineTutorial` uses a `mode_labels` dict for all user-facing mode names:

```python
mode_labels = {
    "tutorial": "Tutorial",
    "advanced": "Advanced Guide",
    "sdk": "SDK Guide",
    "api-reference": "API Reference",
}
```

This drives:
- MkDocs site title: `"{project_name} — {mode_label}"`
- Top-level nav label in `nav_snippet.yml`: `"nav:\n  - {mode_label}:\n..."`
- Index page title: `"# {project_name} — {mode_label}"`
- CLI progress: `emit("COMBINE_FORMAT_MKDOCS", mode=mode_label)`

#### Content-Based Summary Extraction
When `chapter_summaries` from shared store is empty (standard in `api-reference` mode since WriteChapters skips summary generation), the LLM grouping module list builder extracts the first paragraph from each chapter's generated content:
- Skips lines starting with `---`, `#`, `` ``` ``, or empty lines
- Joins remaining lines and truncates to 300 characters
- Falls back to `cf["description"]` if no paragraph found

### `get_content_for_indices` (helper in `nodes.py`)
```python
def get_content_for_indices(files_data, indices):
    # files_data: list of (path, content) tuples
    # Returns: {"i # path": content} for valid indices
    content_map = {}
    for i in indices:
        if 0 <= i < len(files_data):
            path, content = files_data[i]
            content_map[f"{i} # {path}"] = content
    return content_map
```

### `utils/output.py`

> Notes for AI: This is the centralized output utility. ALL user-facing output (stdout prints, log file entries) goes through this module. No code file should use `print()` directly or define ANSI color constants.

**Initialization:**
```python
def init(language="english", use_cache=True, thinking_level=None):
    """Load utils/strings.csv, set language, auto-translate missing strings via LLM.
    Must be called from main() after argument parsing, before any emit() calls.
    Note: `_language` stores capitalized form (e.g., "Vietnamese") for display/LLM prompts. `_lang_col` stores lowercase (e.g., "vietnamese") for CSV column lookups."""
```

**Output functions:**
```python
def emit(key, suffix="", **kwargs):
    """Emit a translatable string to stdout and/or log file.
    - key: STRING_KEY from strings.csv
    - suffix: optional extra text appended (e.g., token breakdown lines)
    - **kwargs: variables to substitute into the template
    Destination (stdout/log/both) and color styling are determined by LEVEL and DEST columns in CSV."""

def emit_raw(level, text, dest="BOTH"):
    """Emit a pre-formatted string with explicit level styling.
    Use for dynamic/structural output not in strings.csv (e.g., token breakdown tables)."""

def get(key, **kwargs):
    """Return raw translated string without printing/logging.
    Use for UI strings embedded in generated markdown (index.md headings, etc.)."""

def configure_logging(project_name="project", mode="tutorial"):
    """Configure file-based logging. Creates logs/{project}_{mode}_{timestamp}.log.
    Moved here from call_llm.py to centralize output concerns."""
```

**String levels and their ANSI colors:**
| Level | ANSI Code | Color | Usage |
|-------|-----------|-------|-------|
| `PROGRESS` | `\033[96m` | Cyan | LLM calls, active steps |
| `SUCCESS` | `\033[92m` | Green | Completions, cache hits |
| `WARNING` | `\033[93m` | Yellow | Warnings, capacity alerts |
| `ERROR` | `\033[91m` | Red | Errors, failures |
| `INFO` | (none) | Plain | Config display, counts |
| `DEBUG` | `\033[90m` | Gray | Skipped files, debug |
| `FILE_WRITE` | (none) | Plain | `  - Wrote {path}` messages |
| `UI` | N/A | N/A | Generated markdown content (not printed) |

**Destination types (DEST column in CSV):**
| DEST | Behavior |
|------|----------|
| `BOTH` | Print to stdout (colored) + log to file (plain) |
| `STDOUT` | Print to stdout only |
| `LOG` | Log to file only |

**Auto-translation flow:**
1. On `init(language, use_cache=True, thinking_level=None)`, load `utils/strings.csv` with `csv.DictReader`.
2. For each row, try: language column → English fallback.
3. If any strings fell back to English (no translation found), batch-translate via LLM using `prompts/common/translate_strings.md`. `use_cache` and `thinking_level` are forwarded to the LLM call.
4. Write translations directly back into `utils/strings.csv` using `_write_translations_to_csv()` with `utf-8-sig` encoding (BOM for Excel compatibility).
5. The CSV write-back adds the language column if it doesn't exist.

## 10. Node Design — Template Variable Contracts

> Notes for AI: This section is THE MOST CRITICAL for correct code generation. Every node that calls an LLM must pass EXACTLY these variables to `prompt_template.format()`. Do NOT invent new variable names.

### How to Build Common Template Variables

> Notes for AI: These exact f-string formats MUST be used. Do not modify them.

```python
# Building "context" (file content block — used by Identify, Map, Analyze, Order):
context = ""
for i, path, content in files:  # 3-tuple format from ContextRouter
    context += f"--- File Index {i}: {path} ---\n{content}\n\n"

# Building "abstraction_listing" (used by Analyze, Order):
abstraction_listing = "\n".join([f"{i} # {abstr['name']}" for i, abstr in enumerate(abstractions)])

# Building "partial_abstractions" (used by Reduce):
partial_abstractions = ""
for i, a in enumerate(mapped_abstractions):
    partial_abstractions += f"- Partial Abstraction {i}: {a['name']}\n  Description: {a['description']}\n  Files: {a['files']}\n\n"
```

### Language Instruction Variables

> Notes for AI: These patterns are used by ALL LLM-calling nodes. Each node constructs them with slightly different wording depending on context.

**MapAbstractions / ReduceAbstractions:**
```python
language_instruction = f"Output language MUST be entirely in {language}. " if language.lower() != "english" else ""
name_lang_hint = f" (in {language})" if language.lower() != "english" else ""
desc_lang_hint = f" (in {language})" if language.lower() != "english" else ""
```

**IdentifyAbstractions** (uses different, more emphatic wording):
```python
language_instruction = f"IMPORTANT: Generate the `name` and `description` for each abstraction in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n" if language.lower() != "english" else ""
name_lang_hint = f" (value in {language.capitalize()})" if language.lower() != "english" else ""
desc_lang_hint = f" (value in {language.capitalize()})" if language.lower() != "english" else ""
```

**AnalyzeRelationships:**
```python
language_instruction = f"IMPORTANT: Generate the `summary` and relationship `label` fields in **{language.capitalize()}** language. Do NOT use English for these fields.\n\n" if language.lower() != "english" else ""
lang_hint = f" (in {language.capitalize()})" if language.lower() != "english" else ""
list_lang_note = f" (Names might be in {language.capitalize()})" if language.lower() != "english" else ""
```

**OrderChapters:**
```python
list_lang_note = f" (Names might be in {language.capitalize()})" if language.lower() != "english" else ""
summary_note = f" (Note: Project Summary might be in {language.capitalize()})" if language.lower() != "english" else ""
# Note: summary_note is prepended to the context string: f"Project Summary{summary_note}:\n..."
# Note: OrderChapters does NOT use language_instruction in the template
```

**WriteChapters (most complex):**
```python
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
    link_lang_note = f" (Use the {lang_cap} chapter title from the structure above)"
    tone_note = f" (appropriate for {lang_cap} readers)"
```

### Per-Node Template Variable Mapping

> Notes for AI: The left column is the exact kwarg name to pass to `.format()`. The right column is where the value comes from.

#### FetchRepo
No LLM call. Reads shared store, calls crawl utility, writes `shared["files"]` and `shared["project_name"]`.

**`prep()` return:** `dict`
```python
return {
    "repo_url": repo_url, "local_dir": local_dir,
    "token": shared.get("github_token"),
    "include_patterns": include_patterns, "exclude_patterns": exclude_patterns,
    "max_file_size": max_file_size, "use_relative_paths": True,
}
```
**`exec()` validation:** Raises `ValueError("No matching files found...")` if 0 files crawled.
**Project name derivation:** `repo_url.split("/")[-1].replace(".git", "")` if URL, else `os.path.basename(os.path.abspath(local_dir))`
**`post()` writes:** `shared["files"] = exec_res` (list of tuples). Returns `None`.

#### ContextRouter
No LLM call. Routes to `"direct"` or `"batch"`. Writes `shared["max_tokens"]`, `shared["file_batches"]`, `shared["directory_tree"]`.

**ContextRouter Algorithm:**
1. Auto-detect `max_tokens` from provider if not set; write to `shared["max_tokens"]`
2. Measure prompt overhead = max(template_tokens across ALL 4 mode subdirs × 3 template types: `identify_abstractions.md`, `map_abstractions.md`, `draft_chapters.md`) + directory_tree_tokens + chapter_listing_tokens (estimated as `"N. basename (doc: path.md)"` per file)
3. `safety_limit = int(max_tokens * 0.95)`; `effective_limit = safety_limit - prompt_overhead`
4. Count total file content tokens using `f"--- File Index {i}: {path} ---\n{content}\n\n"` per file
5. If `total_tokens > effective_limit` OR `force_batch`:
   - Group files by `os.path.dirname(path)` — NEVER mix directories
   - Within each directory group, create batches respecting both `effective_limit` tokens AND `batch_size` file count
   - Return `"batch"`
6. Else: Return `"direct"`

**`build_directory_tree(files_data)` format:**
```
dirname/
  filename.ext (idx:0)
  other.ext (idx:1)
other_dir/
  file.ext (idx:2)
```

**`--debug` output format (when `shared["debug"]` is True):**
```
\033[93m  [Debug] Batch {idx}: {len(batch)} files, ~{content_tokens:,} content tokens (limit: {effective_limit:,})\033[0m
\033[92m    - [{i}] {path}\033[0m
```

**`prep()` return:** 8-element `tuple`
```python
# Direct route:
return ("direct", files_data, effective_limit, batch_size, None, None, directory_tree, False)
# Batch route:
return ("batch", files_data, effective_limit, batch_size, file_token_map, count_tokens, directory_tree, debug)
```
**`post()` writes and return:**
- Direct: returns `"direct"` (does NOT write `file_batches` or `directory_tree` to shared)
- Batch: writes `shared["file_batches"] = exec_res`, `shared["directory_tree"]`, returns `"batch"`

#### IdentifyAbstractions
Template: `prompts/{mode}/identify_abstractions.md`

| `.format()` kwarg | Value source |
|---|---|
| `project_name` | `shared["project_name"]` |
| `context` | Built from `shared["files"]` — see "Building context" above |
| `language_instruction` | Language prefix string |
| `max_abstraction_num` | `shared["max_abstraction_num"]` |
| `name_lang_hint` | `f" (in {lang})"` or `""` |
| `desc_lang_hint` | `f" (in {lang})"` or `""` |
| `directory_tree` | Built from `shared["files"]` via `build_directory_tree()` |

**Expected YAML response:** List of dicts with `name`, `description`, `file_indices`
**Index parsing:** `re.findall(r'\d+', str(idx_entry))` — handles `3`, `"3 # path.py"`, `"0-3"` range formats
**Writes:** `shared["abstractions"] = [{"name": ..., "description": ..., "files": [int, ...]}, ...]`

**`prep()` return:** 11-element `tuple` — `(context, directory_tree, total_files_count, project_name, language, use_cache, max_abstraction_num, thinking_level, advanced_mode, max_tokens, mode)`
**Context truncation:** If total tokens exceed `int(max_tokens * 0.95)`, truncates at that file index with a warning print.
**Range parsing:** `"0-3"` expands to `[0, 1, 2, 3]` via `range(start, end+1)`, NOT "takes first number".
**`post()` return:** `None`

#### MapAbstractions (BatchNode)
Template: `prompts/{mode}/map_abstractions.md`

| `.format()` kwarg | Value source |
|---|---|
| `project_name` | `item["project_name"]` |
| `context` | Built from `item["files"]` (3-tuples from batch) |
| `directory_tree` | `item["directory_tree"]` (full project tree) |
| `language_instruction` | Language prefix |
| `name_lang_hint` | Lang hint |
| `desc_lang_hint` | Lang hint |

**Expected YAML response:** Same as IdentifyAbstractions — `name`, `description`, `file_indices`
**Writes:** `shared["mapped_abstractions"]` — flattened from all batch results

**`prep()` return:** `list[dict]` — each dict has keys: `batch_index`, `files`, `project_name`, `language`, `use_cache`, `thinking_level`, `advanced_mode`, `max_tokens`, `directory_tree`, `mode`
**`post()` return:** `None`

#### ReduceAbstractions
Template: `prompts/{mode}/reduce_abstractions.md`

| `.format()` kwarg | Value source |
|---|---|
| `project_name` | `shared["project_name"]` |
| `partial_abstractions` | String built from mapped_abstractions (see above) |
| `language_instruction` | Language prefix |
| `max_abstraction_num` | `shared["max_abstraction_num"]` |
| `name_lang_hint` | Lang hint |
| `desc_lang_hint` | Lang hint |

**Expected YAML response:** List of dicts with `name`, `description`, `files` (⚠ NOT `file_indices` — uses `files` key here)
**Writes:** `shared["abstractions"]`

**`prep()` return:** 9-element `tuple` — `(mapped_abstractions, project_name, language, use_cache, max_abstraction_num, thinking_level, advanced_mode, max_tokens, mode)`
**`post()` return:** `None`

#### AnalyzeRelationships
Template: `prompts/{mode}/identify_relationships.md`

| `.format()` kwarg | Value source |
|---|---|
| `project_name` | `shared["project_name"]` |
| `abstraction_listing` | `"\n".join([f"{i} # {name}" ...])` |
| `context` | Abstraction listing + TWO-PASS budget-aware file snippets |
| `language_instruction` | Special relationship-specific prefix |
| `list_lang_note` | `f" (Names might be in {lang})"` or `""` |
| `lang_hint` | `f" (in {lang})"` or `""` |

**TWO-PASS Token Budget Algorithm:**
1. Calculate `total_budget = safety_limit - current_context_tokens - 2000` (prompt overhead)
2. `per_abstr_budget = total_budget // num_abstractions`
3. For each abstraction, sort files by token count DESCENDING (largest = most significant)
4. **Pass 1:** Include files up to `per_abstr_budget`. Track `included_indices` for dedup. Record unused budget.
5. **Pass 2:** Redistribute total unused budget to abstractions with remaining files.
6. **Dedup:** Already-included files render as `(File {idx} # {path} -- already shown above)`
7. **Budget exhausted:** Remaining files listed as `Other files (path only, budget exhausted): {list}`

**Expected YAML response:** Dict with `summary` (str), `relationships` (list of `{from_abstraction, to_abstraction, label}`)
**Post-processing:** Parse `from_abstraction`/`to_abstraction` to int indices via `re.findall(r'\d+', ...)`
**Writes:** `shared["relationships"] = {"summary": str, "details": [{"from": int, "to": int, "label": str}, ...]}`

**`prep()` return:** 11-element `tuple` — `(context, abstraction_listing, num_abstractions, project_name, language, use_cache, thinking_level, advanced_mode, max_tokens, max_tokens, max_tokens)`
**`post()` return:** `None`

#### OrderChapters
Template: `prompts/{mode}/order_chapters.md`

| `.format()` kwarg | Value source |
|---|---|
| `project_name` | `shared["project_name"]` |
| `abstraction_listing` | `"\n".join([f"- {i} # {name}" ...])` |
| `context` | Summary + relationship edges formatted as `From {i} ({name}) to {j} ({name}): {label}` |
| `list_lang_note` | `f" (Names might be in {lang})"` or `""` |

**Expected YAML response:** Top-level YAML list of indices `[0, 3, 1, ...]` or `["0 # Name", ...]`
**Validation:** Must cover all abstractions, no duplicates, indices in valid range
**Writes:** `shared["chapter_order"] = [int, ...]`

**`prep()` return:** 11-element `tuple` — `(abstraction_listing, context, num_abstractions, project_name, list_lang_note, use_cache, thinking_level, advanced_mode, max_tokens, max_tokens, max_tokens)`
**`post()` return:** `None`

#### DeterministicFileMapper
Prompt builder: `utils.prompts.build_code_file_filter_prompt(project_name, file_listing)`

Filters non-code files (configs, UI layouts, static assets) and creates a 1:1 mapping of each code file to a documentation module.

- **Module naming:** `clean_name = os.path.basename(file_path)` — basename with file extension
- **Doc filename:** `original_path + '.md'` (preserves original extension, e.g., `utils/call_llm.py.md`)
- **Abstraction dict:** `{"name": clean_name, "description": f"Internal API reference for `{file_path}`", "files": [idx], "original_path": file_path}`
- **Writes:** `shared["abstractions"]`, `shared["chapter_order"]` (sorted by directory depth), `shared["relationships"]`

**`prep()` return:** 4-element `tuple` — `(prompt, use_cache, thinking_level, max_tokens)` (passes `use_cache` from shared store)
**`post()` return:** `"default"`

#### WriteChapters (BatchNode)
Template: `prompts/{mode}/draft_chapters.md`

| `.format()` kwarg | Value source |
|---|---|
| `language_instruction` | Full WriteChapters language block (see above) |
| `project_name` | `shared["project_name"]` |
| `abstraction_name` | `abstractions[idx]["name"]` |
| `chapter_num` | 1-based chapter number |
| `concept_details_note` | Lang note or `""` |
| `abstraction_description` | `abstractions[idx]["description"]` |
| `structure_note` | Lang note or `""` |
| `full_chapter_listing` | Flat numbered chapter listing with doc path mapping. Format: `N. name (doc: path.md)`. Same for all chapters (no per-chapter variation). |
| `current_doc_path` | Current page doc path for LLM relative link computation |
| `directory_tree` | Full project directory structure (from shared store) |
| `prev_summary_note` | Lang note or `""` |
| `previous_chapters_summary` | `"\n---\n".join(self.chapter_summaries)` or `"This is the first chapter."` (empty for api-reference) |
| `file_context_str` | File contents from `get_content_for_indices()` |
| `language` | `shared["language"]` |
| `instruction_lang_note` | Lang note or `""` |
| `link_lang_note` | Lang note or `""` |
| `code_comment_note` | Lang note or `""` |
| `mermaid_lang_note` | Lang note or `""` |
| `tone_note` | (tutorial template only) Lang note or `""` |

**Chapter filename generation:**
```python
# In --mkdocs mode with api-reference (DeterministicFileMapper):
# doc_rel_path = original_path + ".md" (preserves original extension, e.g., utils/call_llm.py.md)
# Standard mode:
safe_name = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
filename = f"{i+1:02d}_{safe_name}.md"
```

**Token usage logging:** Before each LLM call, computes per-component token counts via `count_tokens()`:
- `file_context` — source code for this abstraction's files
- `prev_chapters` — accumulated LLM-generated summaries
- `chapter_listing` — full chapter index
- `overhead` — template + instructions + language notes

**Response token logging:** After each chapter is generated, logs response token count:
- CLI: `\033[92m[Response] Chapter N: X,XXX tokens\033[0m` (green)
- Log: `CHAPTER RESPONSE | chapter=N | name=... | response_tokens=X`

**Heading cleanup:** If response doesn't start with `# Chapter {num}`, prepend or replace first heading.

**Cross-chapter summary workflow:**
1. `self.chapters_written_so_far` accumulates FULL chapter content for output files and incremental cache
2. `self.chapter_summaries` accumulates LLM-generated technical briefs for cross-chapter context
3. After each chapter is written, `build_chapter_summary_prompt()` generates a summary prompt
4. A lightweight LLM call (`thinking_level=None, use_cache=True`) produces a structured brief (4 points × 3-5 sentences)
5. Summary is stored as `"Chapter N — Name:\n{summary}"` in `self.chapter_summaries`
6. Subsequent chapters receive `"\n---\n".join(self.chapter_summaries)` as `previous_chapters_summary`
7. **api-reference mode** skips summaries entirely (independent file docs, no narrative continuity)
8. CLI output: `\033[96m[Summarizing] Chapter N for cross-chapter context (X tokens)...\033[0m` → `\033[96m[Summary Done] Chapter N: X tokens\033[0m` (cyan)
9. Log: `CHAPTER SUMMARY START | chapter=N | prompt_tokens=X` → `CHAPTER SUMMARY DONE | chapter=N | summary_tokens=X`

**Writes:** `shared["chapters"] = [markdown_str, ...]` (list of strings, NOT dicts)
**Writes:** `shared["chapter_summaries"] = [str, ...]` (list of summary strings for LLM nav grouping)

**`prep()` return:** `list[dict]` — each dict contains all metadata for one chapter (chapter_num, abstraction details, prev/next chapter info, etc.)
**`post()` return:** `None`. Also cleans up: `del self.chapters_written_so_far; del self.chapter_summaries`

#### CombineTutorial
Assembles final output files. In `api-reference` + `--mkdocs` mode with 6+ modules, makes **one LLM call** to group modules into sidebar sections.

**LLM-Assisted Nav Grouping (api-reference + --mkdocs only):**
- Loads `prompts/common/group_modules.md` template
- Sends module names + chapter summaries + directory tree to LLM
- LLM returns YAML with hierarchical sections (supports arbitrary nesting via `children`)
- Validates all modules are covered; ungrouped modules → "Other" section
- Fallback: if LLM fails, uses flat nav (all modules listed directly)
- Only triggered for 6+ modules; smaller projects keep flat layout

**Mermaid generation:**
```python
mermaid_lines = ["flowchart TD"]
for i, abstr in enumerate(abstractions):
    sanitized_name = abstr["name"].replace('"', "")
    mermaid_lines.append(f'    A{i}("{sanitized_name}")')
for rel in relationships_data["details"]:
    edge_label = rel["label"].replace('"', "").replace("\n", " ")
    if len(edge_label) > 30: edge_label = edge_label[:27] + "..."
    mermaid_lines.append(f'    A{rel["from"]} -- "{edge_label}" --> A{rel["to"]}')
```

**`full_content.md` TOC:**
```python
toc_lines.append(f"- [{title}](#chapter-{i+1})")
full_content_lines.append(f'<a id="chapter-{i+1}"></a>\n')
```

**`prep()` return:** `dict` with keys: `output_path`, `output_base_dir`, `is_mkdocs`, `chapter_files` (list of `{"filename": str, "content": str, "module_name": str, "description": str, "original_path": str}`), `ui` (translated strings). MkDocs adds: `nav_snippet`, `project_name`, `mode`, `chapter_summaries`, `directory_tree`, `language`, `use_cache`, `thinking_level`, `max_tokens`. Standard adds: `index_content`.
**`exec()` operations:**
- **Standard mode:** Creates output directory, writes `index.md`, individual chapter files, and `full_content.md`.
- **MkDocs mode:** Generates `mkdocs.yml` (via `build_mkdocs_config()` with Material theme, mermaid, panzoom, navigation.indexes), `docs/javascripts/mermaid-init.js` (native Mermaid default theme initializer), `docs/api/index.md` (section landing page with chapter table and relative links), `docs/nav_snippet.yml`, and individual chapter files in `docs/api/`. For `api-reference` mode with 6+ modules, runs LLM grouping to create nested sidebar sections.
**`post()` writes:** `shared["final_output_dir"] = exec_res` (output path string). Returns `None`.



### Node Validation Strictness

> Notes for AI: Each node handles malformed LLM output differently. This table determines whether a node retries (via PocketFlow's retry mechanism) or silently skips bad items.

| Node | Validation Style | Behavior on Invalid Output |
|---|---|---|
| FetchRepo | Strict | Raises `ValueError` if 0 files crawled |
| ContextRouter | N/A | Internal math, no LLM output to validate |
| IdentifyAbstractions | Strict on structure, lenient on indices | Raises `ValueError` if not list, missing keys, or wrong types → triggers retry. Invalid individual indices are silently skipped with a warning. |
| MapAbstractions | Lenient | Silently skips malformed items (missing keys, wrong types). Does NOT raise `ValueError`. |
| ReduceAbstractions | Lenient | Same as MapAbstractions — silently skips invalid items. |
| AnalyzeRelationships | Strict on structure, lenient on indices | Raises `ValueError` if missing `summary`/`relationships` keys or wrong types. Invalid individual relationship indices are skipped with a warning. |
| OrderChapters | Extremely strict | Raises `ValueError` on: non-list output, unparseable index, out-of-bounds, duplicates, incomplete coverage → triggers retry for ALL anomalies. |
| WriteChapters | Auto-correcting | If heading doesn't match `# Chapter {num}: {name}`, auto-prepends/replaces correct heading. |
| CombineTutorial | Lenient on indices | Skips mismatched indices/missing content with a warning print in `prep()`. |

## 11. YAML Response Parsing Rules

> Notes for AI: LLM responses are unpredictable. The parser must handle multiple formats.

### Extraction Pattern

The `parse_yaml_response()` helper uses the split-based approach (primary implementation):
```python
def parse_yaml_response(response):
    yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
    return yaml.safe_load(yaml_str)
```

> Note: Some nodes may alternatively use `re.search(r'```yaml\s*\n(.*?)\n\s*```', response, re.DOTALL)`. Both methods extract the YAML block from fenced code blocks.

### Expected YAML Field Names Per Node

| Node | Top-level | Per-item fields | Notes |
|---|---|---|---|
| IdentifyAbstractions | list | `name`, `description`, `file_indices` | Indices: int or `"3 # path"` |
| MapAbstractions | list | `name`, `description`, `file_indices` | Same |
| ReduceAbstractions | list | `name`, `description`, `files` | ⚠ `files` not `file_indices` |
| AnalyzeRelationships | dict | `summary`, `relationships[].from_abstraction`, `.to_abstraction`, `.label` | |
| OrderChapters | list | Top-level int list | `[0, 3, 1, ...]` |

### Index Validation
```python
def parse_index(idx_value):
    nums = re.findall(r'\d+', str(idx_value))
    if nums: return int(nums[0])
    return None
```
Handles: `3`, `"3 # path/file.py"`, `"0-3"` (IdentifyAbstractions expands range to `[0,1,2,3]` via `range(start, end+1)`; Map/Reduce take first number only)

## 12. Internationalization

> Notes for AI: UI strings and all CLI output strings are stored in `utils/strings.csv`. Do NOT hardcode strings in Python files.

### String Table: `utils/strings.csv`

All user-facing strings (CLI output, generated UI labels) are externalized to `utils/strings.csv`.

**CSV columns:**
| Column | Purpose |
|--------|---------|
| `STRING_KEY` | Unique identifier (UPPER_SNAKE_CASE, e.g., `LLM_CALL_WRITE_CHAPTER`) |
| `LEVEL` | Output level: `PROGRESS`, `SUCCESS`, `WARNING`, `ERROR`, `INFO`, `DEBUG`, `FILE_WRITE`, `UI` |
| `DEST` | Output destination: `BOTH`, `STDOUT`, `LOG` |
| `english` | English text with `{placeholder}` variables |
| `vietnamese` | Vietnamese text (pre-filled for UI strings, empty for CLI → auto-translated) |
| ... | Additional language columns: `chinese`, `japanese`, `korean`, `french`, `spanish`, `german`, `portuguese`, `russian`, `thai`, `indonesian` |

**String key conventions:**
| Prefix | Category | Example |
|--------|----------|---------|
| `LLM_*` | LLM call progress | `LLM_CALL_WRITE_CHAPTER` |
| `DONE_*` | Completion messages | `DONE_IDENTIFIED_ABSTRACTIONS` |
| `WARN_*` | Warnings | `WARN_CONTEXT_TRUNCATED` |
| `CACHE_*` | Cache operations | `CACHE_HIT_SKIP` |
| `COMBINE_*` | CombineTutorial output | `COMBINE_WRITING_OUTPUT` |
| `CFG_*` | Config display labels | `CFG_AI_PROVIDER` |
| `CRAWL_*` | File crawl status | `CRAWL_FILE_PROCESSED` |
| `UI_*` | Generated doc UI labels | `UI_TUTORIAL`, `UI_CHAPTERS` |

**UI string keys (pre-translated for 12 languages):**
| Key | English | Purpose |
|-----|---------|----------|
| `UI_TUTORIAL` | Tutorial | Section heading for generated docs |
| `UI_SOURCE_REPO` | Source Repository | Link label to source |
| `UI_CHAPTERS` | Chapters | Chapter listing heading |
| `UI_TOC` | Table of Contents | TOC heading |
| `UI_CHAPTER` | Chapter | Individual chapter prefix |
| `UI_FULL_CONTENT` | Full Content | Full content link label |

**Usage in code:**
```python
from utils.output import emit, get

# CLI output (prints to stdout with color + logs to file)
emit("LLM_CALL_WRITE_CHAPTER", chapter_num=1, name="flow")

# UI strings for generated markdown (no print, just returns translated text)
ui = {
    "tutorial": get("UI_TUTORIAL"),
    "chapters": get("UI_CHAPTERS"),
    "toc": get("UI_TOC"),
    ...
}
```

**Auto-translation:** Missing language cells in `utils/strings.csv` are auto-translated via LLM at startup and written directly back into the CSV. The `--language` flag controls both generated document language AND CLI output language.

## 13. Error Handling & Retry Configuration

> Notes for AI: Node retry settings are configured in `flow.py`, NOT in node class definitions.

### Retry Configuration
| Node | `max_retries` | `wait` (seconds) |
|---|---|---|
| FetchRepo | 0 (default) | 0 |
| ContextRouter | 0 (default) | 0 |
| MapAbstractions | 5 | 20 |
| ReduceAbstractions | 5 | 20 |
| IdentifyAbstractions | 5 | 20 |
| AnalyzeRelationships | 5 | 20 |
| OrderChapters | 5 | 20 |
| WriteChapters | 5 | 20 |
| DeterministicFileMapper | 5 | 20 |
| CombineTutorial | 0 (default) | 0 |

### LLM Cache-on-Retry Pattern
```python
result = call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)
```
First attempt uses cache; retries always get fresh responses.

### `call_llm` Error Handling
```python
try:
    response = requests.post(url, headers=headers, json=payload, timeout=(10, 300))
    response_json = response.json()
    response.raise_for_status()
    return response_json["choices"][0]["message"]["content"]
except requests.exceptions.HTTPError as e:
    error_details = response.json().get("error", "No additional details")
    raise Exception(f"HTTP error occurred: {e} (Details: {error_details})")
except requests.exceptions.ConnectionError:
    raise Exception(f"Failed to connect to {provider} API.")
except requests.exceptions.Timeout:
    raise Exception(f"Request to {provider} API timed out.")
```

### Cleanup Logic
```python
if args.cleanup:
    # Remove llm_cache.json
    # Remove logs/ directory via shutil.rmtree
```

## 14. Prompt Template Rules

> Notes for AI: Prompt templates are in `prompts/tutorial/`, `prompts/advanced/`, `prompts/api-reference/`, and `prompts/sdk/`. They contain `{placeholder}` variables that form a CONTRACT with the node code.

1. **NEVER paraphrase, truncate, or summarize** prompt templates — copy them byte-for-byte from the originals
2. The `{variable}` placeholders are a CONTRACT — nodes MUST pass exactly matching kwargs to `.format()`
3. To verify correctness: grep each template for `{word}` patterns. Every match must appear as a kwarg in the corresponding node's `.format()` call
4. Templates use Python `.format()` syntax — any literal `{` or `}` in template text MUST be escaped as `{{` or `}}`
5. All 4 directories (`tutorial/`, `advanced/`, `api-reference/`, `sdk/`) have the SAME 6 template files. The `tutorial/` and `advanced/` directories share identical placeholder names. The `api-reference/` and `sdk/` templates may have different placeholder sets (e.g., `api-reference/draft_chapters.md` omits `{tone_note}`, `{chapter_num}`, `{instruction_lang_note}`, `{code_comment_note}`, `{mermaid_lang_note}`).

### Prompt Loading Pattern
```python
# mode is one of: "tutorial", "advanced", "api-reference", "sdk"
prompt_dir = mode  # Directly selects the prompt subdirectory
template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", prompt_dir, f"{template_name}.md")
with open(template_path, "r", encoding="utf-8-sig") as f:
    prompt_template = f.read()
```

### Common Prompts (`prompts/common/`)
Shared prompts that are NOT mode-specific. Loaded directly by path, not via `load_prompt_template()`.

#### `group_modules.md` — LLM Nav Grouping
**Template variables:**
| Variable | Source | Description |
|---|---|---|
| `{project_name}` | `shared["project_name"]` | Project display name |
| `{module_count}` | `len(chapter_files)` | Number of documented modules |
| `{module_list}` | Built from chapter_files + chapter_summaries | `- module_name: summary` per module |
| `{directory_tree}` | `shared["directory_tree"]` | Project directory tree string |
| `{language_note}` | Conditional on `shared["language"]` | `"Section names MUST be in {language}."` or empty |

**Expected YAML response:**
```yaml
sections:
  - name: "Section Name"
    modules: ["module_name_1", "module_name_2"]
  - name: "Parent Section"
    children:
      - name: "Child Section"
        modules: ["module_name_3"]
```

#### `translate_strings.md` — LLM String Translation
**Template variables:**
| Variable | Source | Description |
|---|---|---|
| `{language}` | `--language` argument | The target language to translate strings into |
| `{entries}` | Missing translations from `utils/strings.csv` | List or JSON of strings needing translation |

### Output Format Conventions
Standardized output formats enforced by prompt instructions to ensure consistency across chapters:

| Mode | Convention | Prompt Instruction |
|---|---|---|
| `api-reference` | File path header | `> **Source:** \`path/to/file.ext\`` (blockquote with bold label) |

## 15. Flow Wiring

> Notes for AI: This is the EXACT content of `flow.py`. Reproduce it exactly.

```python
from pocketflow import Flow
from nodes import (
    FetchRepo, ContextRouter, MapAbstractions, ReduceAbstractions,
    IdentifyAbstractions, AnalyzeRelationships, OrderChapters,
    WriteChapters, CombineTutorial, DeterministicFileMapper
)

def create_tutorial_flow():
    fetch_repo = FetchRepo()
    context_router = ContextRouter()
    map_abstractions = MapAbstractions(max_retries=5, wait=20)
    reduce_abstractions = ReduceAbstractions(max_retries=5, wait=20)
    identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters = OrderChapters(max_retries=5, wait=20)
    write_chapters = WriteChapters(max_retries=5, wait=20)
    combine_tutorial = CombineTutorial()
    deterministic_mapper = DeterministicFileMapper(max_retries=5, wait=20)

    fetch_repo >> context_router
    
    context_router - "direct" >> identify_abstractions
    context_router - "batch" >> map_abstractions
    context_router - "deterministic" >> deterministic_mapper

    map_abstractions >> reduce_abstractions
    
    identify_abstractions >> analyze_relationships
    reduce_abstractions >> analyze_relationships
    
    analyze_relationships >> order_chapters
    order_chapters >> write_chapters
    
    deterministic_mapper >> write_chapters
    
    write_chapters >> combine_tutorial

    return Flow(start=fetch_repo)
```

## 16. Code Organization & DRY Patterns

> Notes for AI: Always look for repeated code patterns and extract them into helper functions. When building nodes, check if the pattern you're about to write already exists as a helper. These are not optional suggestions — they are REQUIRED patterns.

### Mindset

As you implement nodes, you will notice recurring operations: loading prompts, parsing YAML, counting tokens, resolving provider config. **Do NOT copy-paste these inline.** Extract them as module-level helpers in `nodes.py` and reuse them. This keeps the codebase maintainable and reduces the surface area for bugs.

### Required Helper Functions

These helpers MUST be defined at the top of `nodes.py`, after imports and before any class definitions:

#### `load_prompt_template(template_name, advanced_mode=False, mode=None)` → `str`
Loads a prompt template from `prompts/{mode}/{template_name}.md`. When `mode` is provided, it directly selects the subdirectory. When `mode` is `None`, falls back to legacy `advanced_mode` boolean.
```python
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
```
**Used by:** MapAbstractions, ReduceAbstractions, IdentifyAbstractions, AnalyzeRelationships, OrderChapters, WriteChapters (6 nodes)

#### `parse_yaml_response(response)` → `Any`
Extracts and parses YAML from an LLM response fenced in ` ```yaml ` blocks.
```python
def parse_yaml_response(response):
    """Extract and parse YAML from an LLM response fenced in ```yaml blocks."""
    try:
        yaml_str = response.strip().split("```yaml")[1].split("```")[0].strip()
        return yaml.safe_load(yaml_str)
    except Exception as e:
        raise ValueError(f"Failed to parse YAML: {e}")
```
**Used by:** MapAbstractions, ReduceAbstractions, IdentifyAbstractions, AnalyzeRelationships, OrderChapters (5 nodes)

#### `create_token_counter()` → `Callable[[str], int]`
Creates a token counting function using tiktoken with char-count fallback.
```python
def create_token_counter():
    """Create a token counting function using tiktoken with char-count fallback."""
    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda text: len(enc.encode(text, disallowed_special=()))
    except Exception:
        return lambda text: len(text) // 4
```
**Used by:** ContextRouter, IdentifyAbstractions, AnalyzeRelationships (3 nodes)

#### `resolve_max_tokens(shared)` → `int`
Resolves max_tokens from shared store or auto-detects from provider environment variables.
```python
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
```
**Used by:** ContextRouter, IdentifyAbstractions (2 nodes)

### Anti-Patterns to Avoid

| ❌ Don't | ✅ Do Instead |
|---|---|
| `prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", ...)` inline in every node | `prompt_template = load_prompt_template("identify_abstractions", advanced_mode)` |
| `yaml_str = response.strip().split("```yaml")[1]...` repeated 5× | `data = parse_yaml_response(response)` |
| `try: enc = tiktoken.get_encoding(...)` in 3 different methods | `count_tokens = create_token_counter()` |
| `provider = os.environ.get("LLM_PROVIDER")` + if/else in 2 nodes | `max_tokens = resolve_max_tokens(shared)` |
| Redefining `import re` inside functions when it's already imported at the top | Use the top-level import |

### When to Create New Helpers

If you find yourself writing the same block of code (≥3 lines) in 2+ nodes, extract it as a module-level helper function. Name it descriptively and add a docstring explaining what it does, what it takes, and what it returns.

### `main.py` Modular Design

`main()` is a short orchestrator (~40 lines). All logic is extracted into module-level functions:

| Function | Signature | Returns | Description |
|---|---|---|---|
| `parse_arguments` | `() -> tuple[ArgumentParser, Namespace]` | `(parser, args)` | All argparse setup; returns parser (for `.error()`) and parsed args |
| `resolve_mode_and_project` | `(args) -> tuple[str, str]` | `(mode, project_name)` | Handles `--advanced` legacy flag, derives project name from args |
| `build_shared_store` | `(args, github_token, mode) -> dict` | shared dict | Constructs the shared store dictionary passed between PocketFlow nodes |
| `detect_llm_config` | `(args) -> tuple[str, str, str, str, int]` | `(provider, model_name, endpoint_url, api_key, context_length)` | Detects LLM provider from env vars, calculates context length |
| `display_config` | `(args, mode, provider, model_name, endpoint_url, context_length, log_file) -> None` | — | Emits all `CFG_*` strings to console |
| `_run_cleanup` | `() -> None` | — | Removes `llm_cache.json` and `logs/` directory |

### Depth-First File Ordering (api-reference mode)

In `DeterministicFileMapper.post()`, `chapter_order` is sorted by directory depth (deepest first, then alphabetical within same depth). This ensures utility/leaf files are processed before orchestration files in `WriteChapters`, making their summaries available as `previous_chapters_summary` context when processing higher-level files.

```python
shared["chapter_order"] = sorted(
    chapter_order,
    key=lambda idx: (-modules[idx]["original_path"].count("/") - modules[idx]["original_path"].count(os.sep), modules[idx]["original_path"].lower()),
)
```

This ordering is **language-agnostic** — it works for any codebase (Python, C#, C++, Java, etc.) because it exploits the universal convention that utility files live in deeper directories.
