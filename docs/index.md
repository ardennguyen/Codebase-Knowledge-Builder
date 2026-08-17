---
layout: default
title: "Home"
nav_order: 1
---

# AI Codebase Knowledge Builder

Ever stared at a new codebase written by others feeling completely lost? This project analyzes GitHub repositories and creates beginner-friendly tutorials explaining exactly how the code works - all powered by AI! Our intelligent system automatically breaks down complex codebases into digestible explanations that even beginners can understand.

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up LLM in `utils/call_llm.py` by providing credentials via a `.env` file. You can use native Gemini by setting `GEMINI_API_KEY`. For OpenRouter, set `LLM_PROVIDER=OPENROUTER` and `OPENROUTER_API_KEY`. 

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
- `--repo` or `--dir` - Specify either a GitHub repo URL or a local directory path (required, mutually exclusive)
- `-n, --name` - Project name (optional, derived from URL/directory if omitted)
- `-t, --token` - GitHub token (or set GITHUB_TOKEN environment variable)
- `-o, --output` - Output directory (default: ./output)
- `-i, --include` - Files to include (e.g., `*.py` `*.js`). Defaults to `*` (all files).
- `-e, --exclude` - Files to exclude. Custom patterns are automatically merged with a massive global exclusion list (build caches, node_modules, binaries, media, AI environments) AND your repository's native `.gitignore` rules.
- `-s, --max-size` - Maximum file size in bytes (default: 100KB)
- `--language` - Language for the generated tutorial (default: "english")
- `--max-abstractions` - Maximum number of abstractions to identify (default: 10)
- `--no-cache` - Disable LLM response caching (default: caching enabled)
- `--thinking-level` - Thinking effort level for native Gemini, OpenRouter, and Ollama reasoning models (e.g., low, medium, high). Leave empty to use model defaults.
- `--max-tokens` - Maximum number of tokens for the context window (default: fetched dynamically from the model).
- `--advanced` - Load advanced prompts from `prompts/advanced/` directory instead of the tutorial prompts.
- `--batch` - Maximum files per batch when using map-reduce mode (default: 50).
- `--force-batch` - Force the pipeline to use map-reduce mode regardless of context limits.

The application will crawl the repository, analyze the codebase structure, generate tutorial content in the specified language, and save the output in the specified directory (default: ./output). This includes individual chapter files, an `index.md`, and a compiled `full_content.md` containing the complete tutorial with a Table of Contents.


*Built using [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a 100-line LLM framework.*

## Generated Tutorials

(No tutorials generated yet. Run the system against a codebase to generate and view tutorials here.)
