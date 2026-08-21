For the project `{project_name}`:

Codebase Context (Batch):
{context}

Full Project Directory Structure:
{directory_tree}

{language_instruction}Analyze the provided codebase context which is a subset (batch) of the entire codebase.
Identify the core abstractions to help those new to the codebase. Focus on "local" abstractions present in this batch.
You MUST preserve core logic, architectural patterns, class structures, and function signatures with minimal loss.

You MUST identify at least 3 abstractions per batch, even if files seem closely related.
Distinguish between: service/logic files vs. data model/schema files vs. configuration/infrastructure files.

This batch is one slice of a larger codebase. The full directory structure is provided above for context.
If you see references to external types, namespaces, or services not present in this batch,
mention them as "external dependencies" in the description but do NOT create abstractions for code you cannot see.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` explaining what it is, its architectural pattern, and core logic with a simple analogy, in around 150-250 words{desc_lang_hint}.
   Include: (a) the core problem it solves, (b) which 2-3 classes or files are most central, (c) a one-sentence note on how it connects to other parts of the system.
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
