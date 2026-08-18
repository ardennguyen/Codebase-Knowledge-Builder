---
layout: default
title: "System Design"
nav_order: 2
---

# System Design: Codebase Knowledge Builder

> Please DON'T remove notes for AI

## Requirements

> Notes for AI: Keep it simple and clear.
> If the requirements are abstract, write concrete user stories

**User Story:** As a developer onboarding to a new codebase, I want a tutorial automatically generated from its GitHub repository or local directory, optionally in a specific language. The system supports two modes: a **tutorial mode** that explains core abstractions with beginner-friendly language, analogies, and code walkthroughs; and an **advanced mode** that produces architecture deep-dives aimed at senior developers or PMs joining a project mid-way, covering design patterns, key dependencies, and practical onboarding notes. The system must also gracefully handle codebases of any size by dynamically switching to a Map-Reduce approach when context limits are reached.

**Input:**
- A publicly accessible GitHub repository URL or a local directory path.
- A project name (optional, will be derived from the URL/directory if not provided).
- Desired language for the tutorial (optional, defaults to English).
- Advanced configurations for token scaling (`--max-tokens`, `--batch`, `--force-batch`), prompting (`--advanced`, `--thinking-level`, `--max-abstractions`), caching (`--no-cache`), debugging (`--debug`), and execution cleanup (`--cleanup`).

**Output:**
- A directory named after the project containing:
    - An `index.md` file with:
        - A high-level project summary (potentially translated).
        - A Mermaid flowchart diagram visualizing relationships between abstractions (using potentially translated names/labels).
        - An ordered list of links to chapter files (using potentially translated names).
        - A link to `full_content.md` at the bottom.
    - Individual Markdown files for each chapter (`01_chapter_one.md`, `02_chapter_two.md`, etc.) detailing core abstractions in a logical order (potentially translated content).
    - A `full_content.md` (inside the project subdirectory) containing all merged chapters and a Table of Contents.

## Flow Design

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
2.  **`ContextRouter`**: Analyzes the total token payload of the fetched files using `tiktoken`. Dynamically calculates **prompt overhead** (template tokens + directory tree tokens) and computes an **effective limit** = `safety_limit - prompt_overhead`. If the file content tokens exceed this effective limit or if `--force-batch` is used, it chunks files into **token-aware, directory-isolated batches** (never mixing files from different directories) and routes to `"batch"`. Also builds a compact directory tree of all files (stored in `shared["directory_tree"]`) for cross-batch awareness. With `--debug`, displays detailed per-batch file lists and token breakdowns. Otherwise, it routes to `"direct"`.
3.  **Path A: Direct**
    *   **`IdentifyAbstractions`**: Analyzes the entire codebase at once to identify core abstractions.
4.  **Path B: Map-Reduce**
    *   **`MapAbstractions` (BatchNode)**: Analyzes each localized directory chunk to extract partial abstractions. Each batch receives the full directory tree for cross-batch awareness.
    *   **`ReduceAbstractions`**: Merges overlapping/partial abstractions into a global list of architecture components.
5.  **`AnalyzeRelationships`**: Takes the unified abstractions list (from either path) and generates a high-level project summary and relationships diagram. Uses token-budget-aware file inclusion: the budget is split evenly across abstractions, with unused budget redistributed in a second pass, maximizing code context without exceeding the context window.
6.  **`OrderChapters`**: Determines the most logical sequence to present the abstractions.
7.  **`WriteChapters` (BatchNode)**: Iterates through the ordered abstractions and writes detailed Markdown chapters using context-aware code inclusion.
8.  **`CombineTutorial`**: Assembles the final outputs including `index.md`, individual chapter files, and a compiled `full_content.md`.

```mermaid
flowchart TD
    A[FetchRepo] --> Router[ContextRouter]
    
    Router -->|direct| B[IdentifyAbstractions]
    Router -->|batch| M1[MapAbstractions]
    M1 --> M2[ReduceAbstractions]
    
    B --> C[AnalyzeRelationships]
    M2 --> C
    
    C --> D[OrderChapters]
    D --> E[Batch WriteChapters]
    E --> F[CombineTutorial]
```

## Utility Functions

> Notes for AI:
> 1. Understand the utility function definition thoroughly by reviewing the doc.
> 2. Include only the necessary utility functions, based on nodes in the flow.

1.  **`crawl_github_files` / `crawl_local_files`**: Handlers for fetching codebase directories/repos. Both produce verbose inline output during crawl with categorized status for each file: processed (green), excluded (gray), size limit (red), and non-text (red). Directories are sorted for deterministic order. A summary is printed at the end with counts for each category.
2.  **`call_llm`** (`utils/call_llm.py`): The core LLM execution wrapper. Supports retries, JSON exception handling, caching, and reasoning tokens.
3.  **`token_utils.py`**:
    *   **`log_token_estimation`**: Calculates tokens dynamically via `tiktoken` (falling back to simple character counting) and prints beautiful analytics metrics (`node_name`, `usage`, `capacity %`) to the CLI just before API execution.

## Node Design

### Shared Store

> Notes for AI: Try to minimize data redundancy

The shared Store structure is organized as follows:

```python
shared = {
    # --- Inputs ---
    "repo_url": None, "local_dir": None, "project_name": None,
    "github_token": None, "output_dir": "output",
    "include_patterns": set(), "exclude_patterns": set(),
    "max_file_size": 200000, "language": "english",
    "use_cache": True, "max_abstraction_num": 10,
    "thinking_level": None, "advanced_mode": False,
    "max_tokens": None, # Dynamic window threshold
    "batch_size": 50, "force_batch": False, # Map-reduce flags
    "debug": False, # Verbose debug output

    # --- Intermediate/Output Data ---
    "files": [], # List of (path, content) tuples
    "directory_tree": "", # Compact tree of all files for cross-batch awareness
    "file_batches": [], # If routed to Map-Reduce, holds chunked file lists
    "mapped_abstractions": [], # Partial abstractions from Map step
    "abstractions": [], # Final unified list (from either Identify or Reduce)
    "relationships": { "summary": None, "details": [] },
    "chapter_order": [],
    "chapters": [],
    "final_output_dir": None
}
```

### Node Steps

> Notes for AI: All active nodes invoke `log_token_estimation` before calling the LLM.

1.  **`FetchRepo`**: Download/read files.
2.  **`ContextRouter`**: Establishes `max_tokens` (fetching dynamically from provider endpoints if needed). Calculates **prompt overhead** (max template tokens + directory tree tokens) and derives an **effective limit** = `(max_tokens * 0.95) - prompt_overhead`. Groups files into token-aware, directory-isolated batches (never mixing files from different directories; each batch stays under the effective limit and under `batch_size` file count). Builds a compact directory tree (`shared["directory_tree"]`) for cross-batch context. With `--debug`, logs per-batch file lists and token counts. Returns `"batch"` or `"direct"`.
3.  **`IdentifyAbstractions`**: (Direct Route) Extracts abstractions and related `file_indices`. Prompts enforce coverage audit and granularity guidance.
4.  **`MapAbstractions`**: (Batch Route) BatchNode that runs chunked files through local abstraction prompts. Each batch item receives the full `directory_tree` for cross-batch awareness (knowing which other files/directories exist outside the current batch). Stores outputs in `mapped_abstractions`.
5.  **`ReduceAbstractions`**: (Batch Route) Standard node that takes all `mapped_abstractions` and merges them via LLM into the final global `abstractions` list. Anti-merge guardrails prevent over-consolidation (different layers, different consumers, or >30 files should not be merged).
6.  **`AnalyzeRelationships`**: Generates high-level project summary and interaction links (`from`, `to`, `label`). Uses **token-budget-aware two-pass file inclusion**: Pass 1 splits the available token budget evenly across all abstractions; Pass 2 redistributes unused budget from abstractions that didn't use their full share. Files are sorted by content size descending (largest = most architecturally significant). Already-shown files are deduplicated across abstractions. Original code comments are preserved as-is (never translated).
7.  **`OrderChapters`**: Identifies linear tutorial flow with dependency-aware constraints (prerequisites before dependents).
8.  **`WriteChapters`**: BatchNode writing Markdown content for each abstraction. Code fidelity enforced: actual source code is preserved verbatim, comments kept as-is.
9.  **`CombineTutorial`**: Assembles outputs into the project subdirectory: `index.md` (with full_content link at the bottom), individual chapter files, and `full_content.md` (table of contents + all chapters merged).
