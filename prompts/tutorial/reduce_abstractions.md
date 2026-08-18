For the project `{project_name}`:

We have identified several partial, overlapping abstractions from different batches of the codebase.

Partial Abstractions:
{partial_abstractions}

{language_instruction}Your task is to merge these overlapping partial abstractions into a cohesive, global list of maximum {max_abstraction_num} core abstractions.

MERGE RULES:
- DO merge: partial abstractions from different batches that clearly describe the same component
  (same class names mentioned, same namespace, overlapping file indices).
- DO merge: a small auxiliary concern (1-3 files) into the larger component it serves.
- DO NOT merge: abstractions at different architectural layers (e.g., network infrastructure + business logic).
- DO NOT merge: abstractions with different consumers (e.g., admin-facing tools + end-user-facing services).
- DO NOT merge if the result would cover more than ~30 files — that's too broad for one chapter; keep them separate.

SIZING GUIDANCE:
- Partial abstractions covering 10+ files likely represent a major subsystem — prefer keeping them standalone.
- Partial abstractions covering 1-3 files may be auxiliary — consider merging into a related larger abstraction.
- If two partial abstractions from the SAME batch are separate, they were distinguished for a reason — don't re-merge them unless clearly redundant.

COVERAGE CHECK: After merging, confirm the total file index set across ALL output abstractions
still covers every file index from the input. Do not silently drop files during merging.

For each merged abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` summarizing the merged concepts, their architectural role, and core logic with a simple analogy, in around 150-200 words{desc_lang_hint}.
3. A merged list of `files` combining all file indices and paths from the input abstractions.

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Global Query Engine{name_lang_hint}
  description: |
    Combined description of the query processing engine.
    It acts as the central hub routing queries to the correct database.{desc_lang_hint}
  files:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
    - 15 # path/to/other_batch_file.js
# ... up to {max_abstraction_num} abstractions
```
