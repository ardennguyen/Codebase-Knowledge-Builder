---
title: "Home"
---

# AI Codebase Knowledge Builder

Ever stared at a new codebase written by others feeling completely lost? This project analyzes GitHub repositories and creates beginner-friendly tutorials explaining exactly how the code works - all powered by AI! Our intelligent system automatically breaks down complex codebases into digestible explanations that even beginners can understand.

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Install dependencies (we highly recommend using a virtual environment of your choice like `venv`, `conda`, `uv`, or `pyenv` to avoid polluting your global system):
   ```bash
   pip install -r requirements.txt
   ```

3. Set up LLM in `utils/call_llm.py` by providing credentials via a `.env` file. You can use native Gemini by setting `GEMINI_API_KEY` (or `GEMINI_PROJECT_ID` for Vertex AI). For OpenRouter, set `LLM_PROVIDER=OPENROUTER` and `OPENROUTER_API_KEY`. 

4. Generate a complete codebase tutorial by running the main script:
    ```bash
    # Analyze a GitHub repository
    python main.py --repo https://github.com/username/repo --include "*.py" "*.js" --exclude "tests/*" --max-size 50000

    # Or, analyze a local directory
    python main.py --dir /path/to/your/codebase --include "*.py" --exclude "*test*"

    # Or, generate a tutorial in Vietnamese
    python main.py --repo https://github.com/username/repo --language "Vietnamese"
    ```

### CLI Options
- `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive).
- `-n, --name` - Project name (optional, derived from repo/directory if omitted).
- `-t, --token` - GitHub personal access token (optional, reads from GITHUB_TOKEN env var if not provided).
- `-o, --output` - Base directory for output (default: ./output).
- `-i, --include` - Files to include (e.g., `*.py` `*.js`). Defaults to `*` (all files).
- `-e, --exclude` - Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native `.gitignore` rules.
- `-s, --max-size` - Maximum file size in bytes (default: 200000, about 200KB).
- `--language` - Language for the generated tutorial (default: english).
  - CLI output language also follows `--language` (translations in `utils/strings.csv`, auto-translated for unsupported languages).
- `--max-abstractions` - Maximum number of abstractions to identify (default: 10).
- `--no-cache` - Disable LLM response caching (default: caching enabled).
- `--thinking-level` - Thinking effort level for native Gemini, OpenRouter, and Ollama reasoning models (e.g., low, medium, high). Leave empty to use model defaults.
- `--max-tokens` - Maximum number of tokens for the context window (default: fetched dynamically).
- `--mode` - Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial).
- `--advanced` - Legacy flag: equivalent to --mode advanced.
- `--mkdocs` - Format output for MkDocs Material (adds YAML frontmatter & nav snippet).
    - Interactive pan/zoom on Mermaid diagrams (`mkdocs-panzoom-plugin`).
    - Custom Mermaid rendering with pan & zoom support.
    - LLM-assisted sidebar grouping for `api-reference` mode (6+ modules auto-clustered into semantic sections).
    - Section index landing page (`api/index.md`) with grouped module table.
    - Run `cd output/<ProjectName> && mkdocs serve` to preview locally (requires `pip install mkdocs-material mkdocs-panzoom-plugin`).
- `--incremental` - Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference).
- `--force-rebuild` - Clear incremental cache and regenerate all chapters from scratch (use with --incremental).
- `--batch` - Maximum files per batch when using map-reduce mode (default: 50).
- `--force-batch` - Force map-reduce mode regardless of context size.
- `--debug` - Enable verbose debug output.
- `--cleanup` - Clean up logs and cache files. Can be used standalone or after a run.

The application will crawl the repository, analyze the codebase structure, generate tutorial content in the specified language, and save the output in the specified directory (default: ./output). This includes individual chapter files, an `index.md`, and a compiled `full_content.md` containing the complete tutorial with a Table of Contents.


*Built using [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a 100-line LLM framework.*

## Generated Tutorials

(No tutorials generated yet. Run the system against a codebase to generate and view tutorials here.)
