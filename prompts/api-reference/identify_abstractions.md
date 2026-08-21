For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Your task is to identify ALL logical API modules, core classes, exported functions, and internal mechanics present in this context. Focus strictly on technical interfaces and architecture grouping.
Do not use beginner analogies. 

COVERAGE RULE: Every file index listed below MUST belong to at least one API module. Do NOT skip any files. Group related classes and functions by their functional domain or package/namespace.

For each API module, provide:
1. A concise `name` for the module (e.g., `AuthenticationClient`, `QueryOptimizer`){name_lang_hint}.
2. A technical `description` detailing its role in the system{desc_lang_hint}.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    AuthenticationClient{name_lang_hint}
  description: |
    Handles OAuth2 token lifecycle and API request signing.{desc_lang_hint}
  file_indices:
    - 2 # src/auth.py
# ... up to {max_abstraction_num} modules
```