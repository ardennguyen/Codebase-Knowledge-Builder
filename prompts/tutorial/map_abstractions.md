For the project `{project_name}`:

Codebase Context (Batch):
{context}

{language_instruction}Analyze the provided codebase context which is a subset (batch) of the entire codebase.
Identify the core abstractions to help those new to the codebase. Focus on "local" abstractions present in this batch.
You MUST preserve core logic, architectural patterns, class structures, and function signatures with minimal loss.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` explaining what it is, its architectural pattern, and core logic with a simple analogy, in around 100 words{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Query Processing{name_lang_hint}
  description: |
    Explains what the abstraction does locally in this batch.
    Preserves core logic and class structures.
    It's like a central dispatcher routing requests.{desc_lang_hint}
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
# ... as many as found in this batch
```
