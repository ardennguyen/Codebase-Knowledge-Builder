# Codebase Knowledge Builder — Agent Orchestration Guide

> This document tells AI agents **how to work** on this project — what to read, how to organize, and how to coordinate subagents. For project-specific implementation details (architecture, function signatures, data flow), see [`docs/design.md`](docs/design.md).

## Phase 0: Learn Before You Build

Before writing ANY code, read these documents in order:

### Step 1: Understand the Framework
Read the PocketFlow framework docs in `docs/pocketflow/`:
1. [`docs/pocketflow/index.md`](docs/pocketflow/index.md) — What PocketFlow is (100-line LLM framework)
2. [`docs/pocketflow/guide.md`](docs/pocketflow/guide.md) — Agentic coding methodology
3. [`docs/pocketflow/core_abstraction/node.md`](docs/pocketflow/core_abstraction/node.md) — Node: `prep()` → `exec()` → `post()` lifecycle
4. [`docs/pocketflow/core_abstraction/flow.md`](docs/pocketflow/core_abstraction/flow.md) — Flow: `>>` and `- "action" >>` wiring
5. [`docs/pocketflow/core_abstraction/communication.md`](docs/pocketflow/core_abstraction/communication.md) — Shared Store pattern
6. [`docs/pocketflow/core_abstraction/batch.md`](docs/pocketflow/core_abstraction/batch.md) — BatchNode: `prep()` returns iterable, `exec()` called per item

**Key takeaways you MUST internalize:**
- `Node.prep(shared)` → reads from shared store, returns data for exec
- `Node.exec(prep_res)` → does the work (LLM call), returns result
- `Node.post(shared, prep_res, exec_res)` → writes to shared store, returns action string for routing
- `BatchNode.prep()` returns a list; `exec()` is called once per item; `post()` gets list of results
- `self.cur_retry` tracks retry count (0 on first attempt)
- Retry config (`max_retries`, `wait`) is set in `flow.py` when instantiating nodes

### Step 2: Understand the Project
Read the project design document:
- [`docs/design.md`](docs/design.md) — **READ THIS ENTIRELY.** It contains:
  - Architecture and flow design (Section 2)
  - Project file structure (Section 3)
  - Dependencies (Section 4)
  - Environment configuration (Section 5)
  - CLI arguments (Section 6)
  - Default exclude patterns (Section 7)
  - Shared store schema with data transformations (Section 8)
  - **Utility interface contracts with EXACT signatures** (Section 9)
  - **Node ↔ Template variable mapping tables** (Section 10) — THE MOST CRITICAL SECTION
  - YAML response parsing rules (Section 11)
  - Internationalization table (Section 12)
  - String externalization & output utility (Section 12, Section 9 — utils/output.py)
  - Error handling & retry config (Section 13)
  - Prompt template rules (Section 14)
  - Flow wiring (Section 15)
  - Code organization & DRY patterns (Section 16)

### Step 3: Read Existing Prompt Templates
Read all 26 prompt template files in `prompts/tutorial/` (6), `prompts/advanced/` (6), `prompts/api-reference/` (6), `prompts/sdk/` (6), and `prompts/common/` (2). These are the LLM instructions and MUST be copied verbatim. Note the `{placeholder}` variables — they form a contract with the node code.

---

## Phase 1: Plan Before You Code

Before implementation, create planning documents:

### Create `docs/work/implementation_plan.md`
Based on your reading of `design.md`, create an implementation plan that:
1. Lists every file to create (from Section 3 of design.md)
2. For each file, lists the key functions/classes to implement
3. Identifies dependencies between files (utils first, then nodes, then flow, then main)
4. Notes any open questions or ambiguities

### Create `docs/work/task.md`
A checklist tracking progress:
```markdown
- [ ] utils/__init__.py
- [ ] utils/token_utils.py
- [ ] utils/call_llm.py
- [ ] utils/crawl_local_files.py
- [ ] utils/crawl_github_files.py
- [ ] utils/output.py
- [ ] utils/strings.csv
- [ ] utils/exclude_patterns.py
- [ ] utils/prompts.py
- [ ] nodes.py
- [ ] flow.py
- [ ] main.py
- [ ] .env.sample
- [ ] requirements.txt
- [ ] prompts/tutorial/* (6 files)
- [ ] prompts/advanced/* (6 files)
- [ ] prompts/api-reference/* (6 files)
- [ ] prompts/sdk/* (6 files)
- [ ] prompts/common/* (2 files)
- [ ] Syntax check (all .py files)
- [ ] Runtime test
```

---

## Phase 2: Implementation Workflow

### Subagent Organization

Use specialized subagents for parallel work:

| Subagent Role | Responsibility | Reads |
|---|---|---|
| **Utilities Builder** | Create all `utils/*.py` files | design.md Section 9 (Interface Contracts) |
| **Output & Strings Builder** | Create `utils/output.py` and `utils/strings.csv` | design.md Section 9 (output.py), Section 12 (utils/strings.csv) |
| **Prompts Copier** | Copy all 26 prompt templates verbatim | Existing `prompts/` directory (5 subdirs) |
| **Nodes & Flow Builder** | Create `nodes.py` and `flow.py` | design.md Sections 8, 10, 11, 13, 15, 16 |
| **Main & Config Builder** | Create `main.py`, `.env.sample`, `requirements.txt` | design.md Sections 4, 5, 6, 7, 8 |

### Build Order
1. **Utilities first** — other files import from `utils/`
2. **Prompts** — can be done in parallel with utilities
3. **Nodes** — depends on utilities being importable
4. **Flow** — depends on nodes being importable
5. **Main** — depends on flow being importable

### Critical Rules During Implementation

1. **NEVER rename function parameters** — `directory` not `directory_path`, `token` not `github_token`
2. **NEVER invent template variable names** — use EXACTLY what design.md Section 10 specifies
3. **NEVER paraphrase prompt templates** — copy byte-for-byte
4. **ALWAYS pass 3-4 args to `log_token_estimation`** — `(node_name, prompt, max_tokens)` required, optional `token_usage` dict for diagnostics
5. **ALWAYS forward `thinking_level`** to `call_llm()` — it's in shared store
6. **ALWAYS use `self.cur_retry`** for cache-on-retry pattern — `call_llm(prompt, use_cache=(use_cache and self.cur_retry == 0), thinking_level=thinking_level)`
7. **NEVER use `print()` directly** — use `emit()` from `utils/output.py` for all CLI output. Use `get()` for UI strings in generated markdown.
8. **NEVER define ANSI color constants** in any file — all styling is handled by `utils/output.py` based on the LEVEL column in `utils/strings.csv`.
9. **NEVER hardcode user-facing strings** — add them to `utils/strings.csv` and reference by STRING_KEY.
10. **Extract common prompt-building patterns to `utils/prompts.py`** — MkDocs config builders, chapter summary prompt builders, and code file filter prompts all belong here. Do NOT inline reusable prompt construction logic in node classes.
11. **Keep `main.py` modular** — argument parsing (`parse_arguments`), mode/project resolution (`resolve_mode_and_project`), shared store construction (`build_shared_store`), LLM config detection (`detect_llm_config`), and config display (`display_config`) are separate functions. `main()` should be a short orchestrator (~40 lines).

---

## Phase 3: Verification

### Syntax Check
After all files are created, run:
```bash
python -c "import ast; [ast.parse(open(f).read()) for f in ['main.py','flow.py','nodes.py','utils/call_llm.py','utils/crawl_local_files.py','utils/crawl_github_files.py','utils/token_utils.py','utils/output.py','utils/exclude_patterns.py','utils/prompts.py']]; print('All files pass syntax check')"
```

### Runtime Test
Ask the user to run both modes:
```bash
# Tutorial/Advanced mode
python main.py --dir <test_directory> --language Vietnamese --advanced --force-batch --batch 50

# API Reference + MkDocs mode (tests LLM grouping, vibrant theme, panzoom, section indexes)
python main.py --dir <test_directory> --mode api-reference --mkdocs --incremental
```
Do NOT run this yourself — the user needs their venv activated.

### Template Variable Verification
For each prompt template, verify that every `{placeholder}` has a matching kwarg in the node's `.format()` call:
```bash
grep -oP '\{[a-z_]+\}' prompts/tutorial/identify_abstractions.md | sort -u
# Then check that each one appears in IdentifyAbstractions.exec()
```

---

## Phase 4: Documentation & Commit

### After Every Fix/Feature

1. **Wait for user confirmation** that both automatic and manual tests pass
2. **Update `docs/design.md`** if any design changes were made (new features, changed interfaces, new CLI args)
3. **Update `README.md`** with any user-facing changes
4. **Update `docs/index.md`** if project documentation structure changed
5. **Commit** with a descriptive message following conventional commits:
   ```
   <type>(<scope>): <summary>
   
   === AREA ===
   - Detail of each change
   ```
6. **Ask user** if they want to push

### When Design Changes

If a new feature or bug fix changes any of these, update `docs/design.md`:
- New CLI argument → Section 6
- New shared store key → Section 8
- Changed function signature → Section 9
- New/changed template variables → Section 10
- New YAML response field → Section 11
- New language support → Section 12
- Changed retry config → Section 13
- New prompt template → Section 14
- New MkDocs feature → Section 9 (utility contracts) + `.github/workflows/deploy-docs.yml`
- New CLI output string → utils/strings.csv + use emit() in code
- New output level or styling → Section 9 (utils/output.py)

### CI Workflow Rules (`.github/workflows/deploy-docs.yml`)

1. **MkDocs config generation:** The CI uses `python3 .github/ci_mkdocs_config.py` to generate `mkdocs.yml` and `mermaid-init.js`. Do NOT use bash heredocs for YAML generation — they silently break indentation.
2. **Nav merge:** The CI creates its own `mkdocs.yml` (with `Home` + `Architecture & Design`) and appends `nav_snippet.yml` via `sed '1d'`. The `nav_snippet.yml` content must use 2-space indent to align with the base nav.
3. **Static docs:** `docs/index.md` stays as `Home`. Generated `api/index.md` is the API Reference section landing page (requires `navigation.indexes` in Material features).
---

## Quick Reference: Where to Find What

| Question | Answer Location |
|---|---|
| What does this project do? | design.md Section 1 |
| What's the architecture? | design.md Section 2 (mermaid diagram) |
| What files do I need to create? | design.md Section 3 |
| What are the exact function signatures? | design.md Section 9 |
| What variables does node X pass to its template? | design.md Section 10 |
| What YAML fields does the LLM response need? | design.md Section 11 |
| How does PocketFlow's Node work? | docs/pocketflow/core_abstraction/node.md |
| How does PocketFlow's BatchNode work? | docs/pocketflow/core_abstraction/batch.md |
| How do I wire the flow graph? | docs/pocketflow/core_abstraction/flow.md |
| How does the output utility work? | design.md Section 9 (utils/output.py) |
| Where are externalized strings? | utils/strings.csv + design.md Section 12 |
| How to add a new CLI output string? | Add to utils/strings.csv, use emit() in code |
| Where are default exclude patterns? | utils/exclude_patterns.py |
| Where are node helper functions? | design.md Section 16 |
| Where are prompt builders? | design.md Section 9 (utils/prompts.py) |