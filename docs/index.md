---
title: "Home"
---

# AI Codebase Knowledge Builder

Ever stared at a new codebase feeling completely lost? This project analyzes GitHub repositories or local directories and generates structured documentation — from beginner-friendly tutorials to exhaustive API references — all powered by AI. Choose from 4 documentation modes to match your audience, and optionally deploy as a full MkDocs site.

## 🚀 Getting Started

1. Clone this repository
   ```bash
   git clone https://github.com/ardennguyen/Codebase-Knowledge-Builder
   ```

2. Install dependencies (we highly recommend using a virtual environment of your choice like `venv`, `conda`, `uv`, or `pyenv` to avoid polluting your global system):
   ```bash
   pip install -r requirements.txt
   ```

3. Set up LLM by copying `.env.sample` to `.env` and providing credentials. Native Gemini: set `GEMINI_API_KEY` (or `GEMINI_PROJECT_ID` for Vertex AI). OpenRouter: set `LLM_PROVIDER=OPENROUTER` and `OPENROUTER_API_KEY`. Ollama: set `LLM_PROVIDER=OLLAMA` and `OLLAMA_BASE_URL=http://localhost:11434`. Claude (native): set `LLM_PROVIDER=ANTHROPIC` and either `ANTHROPIC_API_KEY` or — without a key — sign in once with the `ant` CLI (`ant auth login`; install with `winget install Anthropic.Ant` on Windows, `brew install anthropics/tap/ant` on macOS, [its releases](https://github.com/anthropics/anthropic-cli/releases) on Linux, or `go install github.com/anthropics/anthropic-cli/cmd/ant@latest`). Default model `claude-sonnet-5`; optional `ANTHROPIC_*` settings in `.env.sample`. Without a key, `main.py` and `utils/call_llm.py` run `ant auth status` before any LLM call and print setup instructions if something is missing.

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
- `--thinking-level` - Global thinking effort for every LLM call: `minimal`, `low`, `medium`, `high`, `xhigh`, `max` (`default` = model default). Overrides `--thinking-profile`. Mapped per provider (Anthropic effort — a thinking budget on Haiku 4.5; Gemini `thinking_level` on 3.x, thinking budget on 2.5; OpenRouter reasoning effort or budget; Ollama reasoning effort — clamped to what the model supports).
- `--thinking-profile` - Per-node effort profile: `auto` (default: `balanced` on `ANTHROPIC`, `GEMINI` and `OPENROUTER`, model defaults elsewhere), `off`, `economy`, `balanced`, `quality`, `max`. Abstraction discovery gets the most effort, chapter writing and ordering a moderate amount, and mechanical steps (summaries, translation, file filtering) the least; shipped profiles stop at `high` except `max`. The effective per-node plan is printed at startup (`Thinking Plan:`).
- `--thinking-override` - Per-node overrides, e.g. `--thinking-override write_chapters=high identify_abstractions=xhigh`. Nodes: `filter_files`, `map_abstractions`, `reduce_abstractions`, `identify_abstractions`, `analyze_relationships`, `order_chapters`, `write_chapters`, `chapter_summary`, `group_modules`, `translate_strings`.
- `--max-tokens` - Maximum number of tokens for the context window (default: fetched dynamically).
- `--mode` - Documentation style (tutorial, advanced, api-reference, sdk). (default: tutorial).
- `--advanced` - Legacy flag: equivalent to --mode advanced.
- `--mkdocs` - Format output for MkDocs Material (adds YAML frontmatter & nav snippet).
    - Interactive pan/zoom on Mermaid diagrams (`mkdocs-panzoom-plugin`).
    - Custom Mermaid rendering with pan & zoom support.
    - LLM-assisted sidebar grouping for `api-reference` mode (6+ modules auto-clustered into semantic sections, in reading order: shared types, then entry points and setup, then the core, supporting and cross-cutting modules last).
    - Section index landing page (`api/index.md`) with grouped module table and one-line module descriptions; in `api-reference` mode also an architecture overview (sections and their dependencies) and a module dependency graph, both from the same grouping call. Tutorial/advanced/SDK landing pages show the project summary and relationship diagram.
    - Run `cd output/<ProjectName> && mkdocs serve` to preview locally (requires `pip install mkdocs-material mkdocs-panzoom-plugin`).
- `--incremental` - Enable MD5 incremental caching to skip unchanged modules (Only supported in --mode api-reference).
- `--force-rebuild` - Clear incremental cache and regenerate all chapters from scratch (use with --incremental).
- `--batch` - Maximum files per batch when using map-reduce mode (default: 50).
- `--force-batch` - Force map-reduce mode regardless of context size.
- `--debug` - Enable verbose debug output.
- `--cleanup` - Clean up logs and cache files. Can be used standalone or after a run.

The application will crawl the repository, analyze the codebase structure, generate tutorial content in the specified language, and save the output in the specified directory (default: ./output). This includes individual chapter files, an `index.md`, and a compiled `full_content.md` containing the complete tutorial with a Table of Contents.


*Built using [Pocket Flow](https://github.com/The-Pocket/PocketFlow), a 100-line LLM framework.*

*Licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/): free for non-commercial use (personal, academic, research); commercial use requires a separate license ([open an issue](https://github.com/ardennguyen/Codebase-Knowledge-Builder/issues)). Derived from [PocketFlow Tutorial-Codebase-Knowledge](https://github.com/The-Pocket/PocketFlow-Tutorial-Codebase-Knowledge) (MIT). See [LICENSE](https://github.com/ardennguyen/Codebase-Knowledge-Builder/blob/main/LICENSE) and [NOTICE](https://github.com/ardennguyen/Codebase-Knowledge-Builder/blob/main/NOTICE).*

## Documentation Modes

| Mode | Audience | Description |
|---|---|---|
| `tutorial` | Beginners | Step-by-step walkthrough of key concepts with gentle explanations |
| `advanced` | Senior devs / PMs | Architectural deep-dive with implementation details and data structures |
| `api-reference` | Developers | Exhaustive per-file API documentation with public/internal separation |
| `sdk` | Integration devs | SDK-oriented docs focused on public API, configuration, and usage patterns |
