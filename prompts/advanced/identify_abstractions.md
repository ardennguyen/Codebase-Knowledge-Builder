For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core architectural abstractions and API components for an advanced developer documentation reference.

For each abstraction, provide:
1. A precise, technically accurate `name`{name_lang_hint}.
2. A technical `description` detailing its architectural role, design patterns used, and core API responsibilities in around 100 words{desc_lang_hint}. Avoid basic analogies; use professional software engineering terminology.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Query Execution Engine{name_lang_hint}
  description: |
    Orchestrates the execution of logical query plans. Implements the Volcano model for iterator-based processing, managing parallel tasks and stateful operations across nodes.{desc_lang_hint}
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
- name: |
    AST Node Factory{name_lang_hint}
  description: |
    Provides the factory pattern implementation for constructing the Abstract Syntax Tree during parsing.{desc_lang_hint}
  file_indices:
    - 5 # path/to/another.js
# ... up to {max_abstraction_num} abstractions
```
