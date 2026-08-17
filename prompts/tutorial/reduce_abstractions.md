For the project `{project_name}`:

We have identified several partial, overlapping abstractions from different batches of the codebase.

Partial Abstractions:
{partial_abstractions}

{language_instruction}Your task is to merge these overlapping partial abstractions into a cohesive, global list of maximum {max_abstraction_num} core abstractions.
Merge abstractions that conceptually belong together or describe the same architectural component.

For each merged abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` summarizing the merged concepts, their architectural role, and core logic with a simple analogy, in around 100 words{desc_lang_hint}.
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
