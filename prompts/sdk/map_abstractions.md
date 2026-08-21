For the project `{project_name}`:

Codebase Context (Batch):
{context}

Full Project Directory Structure:
{directory_tree}

{language_instruction}Analyze this batch of the codebase. Your task is to identify ALL logical API modules, classes, and internal functions in this batch.
Do not use beginner analogies. Focus strictly on grouping by technical interfaces and architecture.

You MUST preserve core logic, architectural patterns, class structures, and function signatures.
Group related classes/functions into logical modules. Identify at least 3 modules per batch.

For each API module, provide:
1. A concise `name` for the module{name_lang_hint}.
2. A technical `description` detailing its role and public API surface{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    QueryOptimizer{name_lang_hint}
  description: |
    Optimizes AST trees before execution.{desc_lang_hint}
  file_indices:
    - 5 # src/query/optimizer.py
# ... as many as found in this batch
```