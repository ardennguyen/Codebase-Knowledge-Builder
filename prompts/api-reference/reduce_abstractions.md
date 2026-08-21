For the project `{project_name}`:

We have identified several partial, overlapping API modules from different batches of the codebase.

Partial Modules:
{partial_abstractions}

{language_instruction}Your task is to merge these overlapping partial modules into a cohesive, global list of maximum {max_abstraction_num} core API modules.

MERGE RULES:
- DO merge: partial modules from different batches that clearly belong to the same functional package.
- DO NOT merge: modules at different architectural layers.
- COVERAGE CHECK: After merging, confirm the total file index set across ALL output modules covers every file index from the input.

For each merged module, provide:
1. A concise `name`{name_lang_hint}.
2. A technical `description` summarizing the module's role{desc_lang_hint}.
3. A merged list of `files` combining all file indices and paths from the input.

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    GlobalQueryEngine{name_lang_hint}
  description: |
    Combined query processing engine API.{desc_lang_hint}
  files:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
# ... up to {max_abstraction_num} modules
```