<!-- NOTE: This template is NOT used in the current api-reference flow.
     ContextRouter routes api-reference mode to DeterministicFileMapper,
     which bypasses abstraction discovery entirely (1:1 file mapping).
     Kept for potential future use if api-reference adds a non-deterministic path. -->

For the project `{project_name}`:

We have identified several partial, overlapping API modules from different batches of the codebase.

Partial Modules:
{partial_abstractions}

{language_instruction}Your task is to merge these overlapping partial modules into a cohesive, global list of maximum {max_abstraction_num} core API modules.

MERGE RULES:
- DO merge: partial modules from different batches that clearly describe the same component (same class names mentioned, same namespace, overlapping file indices).
- DO merge: a small auxiliary concern (1-3 files) into the larger module it serves.
- DO NOT merge: modules at different architectural layers (e.g., network infrastructure + business logic).
- DO NOT merge: modules with different consumers (e.g., admin-facing tools + end-user-facing services).
- DO NOT merge if the result would cover more than ~30 files — that is too broad for one reference page; keep them separate.

SIZING GUIDANCE:
- Partial modules covering 10+ files likely represent a major subsystem — prefer keeping them standalone.
- Partial modules covering 1-3 files may be auxiliary — consider merging into a related larger module.
- If two partial modules from the SAME batch are separate, they were distinguished for a reason — don't re-merge them unless clearly redundant.

COVERAGE CHECK: After merging, confirm the total file index set across ALL output modules
still covers every file index from the input. Do not silently drop files during merging.

For each merged module, provide:
1. A concise `name`{name_lang_hint}.
2. A technical `description` of 100-250 words summarizing the module's role in the system{desc_lang_hint}.
   Include key classes/interfaces, their responsibilities, and critical dependencies.
3. A merged list of `files` combining all file indices and paths from the input modules.

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    GlobalQueryEngine{name_lang_hint}
  description: |
    Combined query processing engine API. Provides the QueryPlanner for logical plan generation, the Optimizer for cost-based rewriting, and the Executor for distributed evaluation.{desc_lang_hint}
  files:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
    - 15 # path/to/other_batch_file.js
# ... up to {max_abstraction_num} modules
```