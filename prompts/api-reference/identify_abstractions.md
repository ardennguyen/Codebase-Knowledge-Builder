<!-- NOTE: This template is NOT used in the current api-reference flow.
     ContextRouter routes api-reference mode to DeterministicFileMapper,
     which bypasses abstraction discovery entirely (1:1 file mapping).
     Kept for potential future use if api-reference adds a non-deterministic path. -->

For the project `{project_name}`:

Codebase Context:
{context}

Full Project Directory Structure:
{directory_tree}

{language_instruction}Your task is to identify ALL logical API modules, core classes, exported functions, and internal mechanics present in this context to produce an exhaustive API reference.
Focus strictly on technical interfaces and architecture grouping. Do not use beginner analogies.

COVERAGE RULE: Every file index listed below MUST belong to at least one API module.
After forming your initial modules, scan the file listing to verify no files are unassigned.
If any files are orphaned, either create a new module or expand an existing one.
Do NOT skip files just because they contain only data models, configuration, or simple boilerplate —
these define the system's data contracts and operational boundaries.

GRANULARITY GUIDANCE:
- Group files that belong to the same package/namespace and expose related interfaces into ONE module.
- Keep files that serve fundamentally different architectural roles in SEPARATE modules, even if co-located in the same directory (e.g., controllers vs. data access layer vs. middleware).
- Data model / schema / DTO files should be grouped with the module that primarily consumes them, NOT lumped into a catch-all "Models" or "Types" module.
- If a single directory contains 20+ files, it likely spans multiple API modules — don't force them into one.

For each API module, provide:
1. A concise `name` for the module (e.g., `AuthenticationClient`, `QueryOptimizer`){name_lang_hint}.
2. A technical `description` of 100-250 words detailing its role in the system{desc_lang_hint}.
   Include: (a) its functional responsibility and WHY it exists as a separate module,
   (b) key public classes/interfaces and their purpose,
   (c) its critical dependencies on other modules.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    AuthenticationClient{name_lang_hint}
  description: |
    Handles OAuth2 token lifecycle and API request signing. Provides the TokenManager class for automatic token refresh and the AuthMiddleware for request interception. Depends on the NetworkTransport module for HTTP calls.{desc_lang_hint}
  file_indices:
    - 2 # src/auth.py
    - 7 # src/auth_middleware.py
# ... up to {max_abstraction_num} modules
```