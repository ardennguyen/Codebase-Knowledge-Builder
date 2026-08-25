# Codebase Knowledge Builder — Agent Guide

> This document tells AI agents **how to work** on this mature project — what to read, how to navigate, how to verify changes, and how to commit. For project-specific implementation details (architecture, function signatures, data flow), see [`docs/design.md`](docs/design.md).

---

## 0. Development Environment

| Item | Value |
|---|---|
| **OS** | Windows 11 |
| **Shell** | `pwsh` (PowerShell 7+) |
| **Python** | 3.12 (managed via `pyenv-win`, venv at `~\.pyenv-win-venv\envs\pocketflow`) |
| **Venv activation** | `& "$env:USERPROFILE\.pyenv-win-venv\envs\pocketflow\Scripts\Activate.ps1"` |
| **Package manager** | `pip` (no `uv`) |
| **Linter/Formatter** | Ruff (configured in `pyproject.toml`) |
| **Git hooks** | pre-commit runs `ruff check` and `ruff format` on every commit |
| **Test output dirs** | `output-test*/` (gitignored, used for local test runs) |

### Windows-Specific Gotchas

- **Encoding:** All `.py` files are UTF-8. When reading files in helper scripts, ALWAYS pass `encoding='utf-8'` to `open()`. Windows defaults to CP1252.
- **No `python -c` one-liners:** PowerShell quote escaping is fragile for multi-line Python. Write a `.py` file to `.agents/scratch/` and run `python .agents/scratch/script_name.py` instead.
- **No Linux CLI tools:** Do NOT use `grep -oP`, `sed`, `awk`, or other POSIX tools. Use PowerShell equivalents (`Select-String`, `Get-Content`, etc.) or Python scripts.

---

## 1. Project Understanding (What to Read First)

Before modifying ANY code, read these documents:

### Step 1: Understand the Framework
Read the PocketFlow framework docs in `docs/pocketflow/`:
1. [`docs/pocketflow/index.md`](docs/pocketflow/index.md) — What PocketFlow is (100-line LLM framework)
2. [`docs/pocketflow/guide.md`](docs/pocketflow/guide.md) — Agentic coding methodology
3. [`docs/pocketflow/core_abstraction/node.md`](docs/pocketflow/core_abstraction/node.md) — Node: `prep()` → `exec()` → `post()` lifecycle
4. [`docs/pocketflow/core_abstraction/flow.md`](docs/pocketflow/core_abstraction/flow.md) — Flow: `>>` and `- "action" >>` wiring
5. [`docs/pocketflow/core_abstraction/communication.md`](docs/pocketflow/core_abstraction/communication.md) — Shared Store pattern
6. [`docs/pocketflow/core_abstraction/batch.md`](docs/pocketflow/core_abstraction/batch.md) — BatchNode: `prep()` returns iterable, `exec()` called per item

**Key internals:**
- `Node.prep(shared)` → reads from shared store, returns data for exec
- `Node.exec(prep_res)` → does the work (LLM call), returns result
- `Node.post(shared, prep_res, exec_res)` → writes to shared store, returns action string for routing
- `BatchNode.prep()` returns a list; `exec()` is called once per item; `post()` gets list of results
- `self.cur_retry` tracks retry count (0 on first attempt)
- Retry config (`max_retries`, `wait`) is set in `flow.py` when instantiating nodes

### Step 2: Understand the Project
- [`docs/design.md`](docs/design.md) — **READ THIS ENTIRELY.** It is the single source of truth for architecture, function signatures, data flow, prompt contracts, and output formats.

### Step 3: Read Prompt Templates
Read all 26 prompt files in `prompts/tutorial/` (6), `prompts/advanced/` (6), `prompts/api-reference/` (6), `prompts/sdk/` (6), and `prompts/common/` (2: `group_modules.md`, `translate_strings.md`). The `{placeholder}` variables form a CONTRACT with the node code.

---

## 2. File & Artifact Storage Policy

| Content type | Save to | Tracked by git? |
|---|---|---|
| Final source code | `utils/`, `nodes.py`, `flow.py`, `main.py` | Yes |
| Prompt templates | `prompts/{mode}/` | Yes |
| Project documentation | `docs/` | Yes |
| Reusable helper scripts (validators, parsers) | `.agents/work/` | **No** (gitignored) |
| One-off scratch scripts, temp data, debug dumps | `.agents/scratch/` | **No** (gitignored) |
| String definitions | `utils/strings.csv` | Yes |

> **NEVER save project files to the Antigravity brain directory** (`~/.gemini/antigravity/brain/<id>/`). That directory is ephemeral, conversation-scoped, and triggers filesystem permission prompts on Windows. Use `.agents/scratch/` for throwaway files and `.agents/work/` for reusable helpers.

---

## 3. Implementation Rules

1. **NEVER rename function parameters** — `directory` not `directory_path`, `token` not `github_token`
2. **NEVER invent template variable names** — use EXACTLY what `design.md` Section 10 specifies
3. **NEVER paraphrase prompt templates** — copy byte-for-byte
4. **ALWAYS pass 3-4 args to `log_token_estimation`** — `(node_name, prompt, max_tokens)` required, optional `token_usage` dict for diagnostics
5. **ALWAYS forward `thinking_level`** to `call_llm()` — it's in shared store
6. **ALWAYS use `self.cur_retry`** for cache-on-retry pattern — `call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)`
7. **NEVER use `print()` directly** — use `emit()` from `utils/output.py` for all CLI output. Use `get()` for UI strings in generated markdown.
8. **NEVER define ANSI color constants** in any file — all styling is handled by `utils/output.py` based on the LEVEL column in `utils/strings.csv`.
9. **NEVER hardcode user-facing strings** — add them to `utils/strings.csv` and reference by STRING_KEY.
10. **Extract common prompt-building patterns to `utils/prompts.py`** — MkDocs config builders, chapter summary prompt builders, and code file filter prompts all belong here.
11. **Keep `main.py` modular** — argument parsing (`parse_arguments`), mode/project resolution (`resolve_mode_and_project`), shared store construction (`build_shared_store`), LLM config detection (`detect_llm_config`), and config display (`display_config`) are separate functions. `main()` is a short orchestrator (~40 lines).
12. **Script execution on Windows** — Do NOT use `python -c "..."` for multi-line scripts. Write a `.py` file to `.agents/scratch/` and run `python .agents/scratch/script_name.py`.
13. **File encoding** — Always pass `encoding='utf-8'` to `open()` in any helper script. Windows defaults to CP1252.

### `utils/strings.csv` Schema

| Column | Description |
|---|---|
| `STRING_KEY` | Unique key used in `emit("KEY")` / `get("KEY")` calls |
| `LEVEL` | `INFO`, `SUCCESS`, `WARNING`, `ERROR`, `DEBUG`, `HEADER` — controls ANSI styling |
| `DEST` | `STDOUT`, `BOTH` (stdout + log), or `LOG` — controls where output goes |
| `EN` | English template string with `{placeholder}` variables |
| Remaining columns | Language translations (auto-filled by LLM via `translate_strings.md`) |

### `emit()` / `get()` Contract
- `emit(key, **kwargs)` — looks up `key` in `strings.csv`, formats with `kwargs`, prints to stdout/log with ANSI styling based on LEVEL
- `get(key, **kwargs)` — same lookup and format, returns the string WITHOUT printing (for embedding in generated markdown)
- `emit_raw(text, level)` — prints raw text with level-based styling, no key lookup

---

## 4. Verification & Testing

### Syntax/Lint Check
```powershell
ruff check .
ruff format --check .
```

### Runtime Tests (ask user to run — do NOT run yourself)
```powershell
# API Reference + MkDocs (most complete test)
python main.py --dir . --mode api-reference --mkdocs --incremental --no-cache --language English

# Tutorial mode (regression test)
python main.py --dir . --mode tutorial --mkdocs --no-cache

# SDK mode
python main.py --dir . --mode sdk --no-cache

# Standalone (no MkDocs)
python main.py --dir . --mode api-reference --no-cache

# With cleanup
python main.py --cleanup
```

### Template Variable Check (PowerShell)
```powershell
# Find all placeholders in a prompt template
Select-String -Path "prompts/tutorial/identify_abstractions.md" -Pattern '\{[a-z_]+\}' -AllMatches |
  ForEach-Object { $_.Matches.Value } | Sort-Object -Unique

# Verify each placeholder has a matching kwarg in the node's .format() call
```

### String Key Alignment Check
```powershell
# Find all emit/get keys in Python code
Select-String -Path "*.py","utils/*.py" -Pattern '"([A-Z_]+)"' -AllMatches |
  ForEach-Object { $_.Matches | ForEach-Object { $_.Groups[1].Value } } | Sort-Object -Unique

# Compare against keys in strings.csv
(Get-Content utils/strings.csv | Select-Object -Skip 1) | ForEach-Object { ($_ -split ',')[0] } | Sort-Object -Unique
```

---

## 5. CI/CD Architecture

### Workflows
- `.github/workflows/deploy-docs.yml` — Auto-generates API docs on push to `main`
- `.github/workflows/lint.yml` — Runs `ruff check .` and `ruff format --check .`

### CI Doc Generation Pipeline
1. **Prompt change detection:** `git diff "$BEFORE" HEAD --name-only | grep -q 'prompts/'` → sets `--force-rebuild`
2. **Doc cache:** `actions/cache@v6` caches `.doc_cache_manifest.json` and `output/.../docs/api/`
3. **Config generation:** `python3 .github/ci_mkdocs_config.py` generates `mkdocs.yml` and `mermaid-init.js`
4. **Nav merge:** `sed '1d'` strips first line of `nav_snippet.yml` and appends to base nav
5. **Deploy:** `mkdocs gh-deploy --force`

### CI Rules
- Do NOT use bash heredocs for YAML generation — they silently break indentation. Use `ci_mkdocs_config.py` instead.
- `nav_snippet.yml` must use 2-space indent to align with the base nav.
- `docs/index.md` is "Home". Generated `api/index.md` is the API Reference section landing page (requires `navigation.indexes` in Material features).
- Manual dispatch input `force_rebuild` can trigger a full rebuild.

---

## 6. Prompt Template Standards

See `docs/design.md` Section 14 for the canonical specification. Key rules:

### Prompt-Code Contract
- Templates use Python `.format()` — any literal `{` or `}` MUST be escaped as `{{` or `}}`
- The `{variable}` placeholders in prompt files are a CONTRACT — nodes MUST pass exactly matching kwargs
- All 4 mode directories have the same 6 template files, but placeholder sets may differ between modes

### Mandatory Page Skeletons (in `draft_chapters.md`)
| Mode | `##` Headings |
|---|---|
| `tutorial` | Motivation & Use Case → Key Concepts → How It Works → Under the Hood → Summary |
| `advanced` | Technical Overview → Implementation Deep-Dive → Data Structures → Error Handling → Practical Notes |
| `api-reference` | Technical Overview → Public API → Internal Helpers → Data Structures → Error Handling → See Also |
| `sdk` | Technical Overview → Public API → Configuration & Options → Data Structures → Error Handling → See Also |

### Other Prompt Rules
- **Proportional depth:** Documentation depth scales with logical complexity, NOT line count
- **ASCII ban (ABSOLUTE):** NEVER use ASCII art — all diagrams must be fenced ` ```mermaid ` blocks
- **Mermaid:** `flowchart TD` only, rectangular nodes, `classDef entryNode` styling, no `%%{{init}}%%`
- **Data Structures:** Mandatory in api-reference, sdk, and advanced modes
- **Code fidelity:** Preserve exact code and original comments — never translate inside code fences
- **Skeleton headings:** MUST be translated to the target `{language}`

---

## 7. Documentation & Commit Workflow

### When Design Changes
If a new feature or bug fix changes any of these, update `docs/design.md`:
- New CLI argument → Section 6
- New shared store key → Section 8
- Changed function signature → Section 9
- New/changed template variables → Section 10
- New YAML response field → Section 11
- New language support → Section 12
- Changed retry config → Section 13
- New prompt template or prompt rule → Section 14
- New MkDocs feature → Section 9 + `.github/workflows/deploy-docs.yml`
- New CLI output string → `utils/strings.csv` + use `emit()` in code
- New output level or styling → Section 9 (`utils/output.py`)

### Commit Policy
- Commit **after each logical feature or fix is complete and verified**
- Every commit message MUST cover **all files changed**, grouped by area:
  ```
  <type>(<scope>): <short summary>

  === AREA NAME ===
  - Bullet describing each meaningful change
  ```
- **Types:** `feat` / `fix` / `refactor` / `chore` / `docs`
- Before committing: inspect `git diff --stat HEAD` — every modified file must appear in the message
- Use `git commit -F <file>` for long messages (write to `.agents/scratch/commit_msg.txt`)

### ❌ Never do these without explicit user instruction
- Version bumps
- `git tag`
- `git push` or `git push --tags` (After EVERY commit, proactively ask the user if they want you to push)
- Branch creation or switching
- Merging or rebasing

---

## 8. Quick Reference

| Question | Answer Location |
|---|---|
| What does this project do? | `design.md` Section 1 |
| What's the architecture? | `design.md` Section 2 (mermaid diagram) |
| What files exist? | `design.md` Section 3 |
| What are the exact function signatures? | `design.md` Section 9 |
| What variables does node X pass to its template? | `design.md` Section 10 |
| What YAML fields does the LLM response need? | `design.md` Section 11 |
| How does PocketFlow's Node work? | `docs/pocketflow/core_abstraction/node.md` |
| How does PocketFlow's BatchNode work? | `docs/pocketflow/core_abstraction/batch.md` |
| How do I wire the flow graph? | `docs/pocketflow/core_abstraction/flow.md` |
| How does the output utility work? | `design.md` Section 9 (`utils/output.py`) |
| Where are externalized strings? | `utils/strings.csv` + `design.md` Section 12 |
| Where are default exclude patterns? | `utils/exclude_patterns.py` |
| Where are node helper functions? | `design.md` Section 16 |
| Where are prompt builders? | `design.md` Section 9 (`utils/prompts.py`) |
| What are the prompt page skeletons? | `design.md` Section 14 |
| How does CI deploy docs? | `design.md` Section 14 + `.github/workflows/deploy-docs.yml` |
| What mode labels exist? | `main.py` → `mode_labels` dict |