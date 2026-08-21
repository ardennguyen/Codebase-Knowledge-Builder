For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core most important abstractions to help those new to the codebase.

COVERAGE RULE: Every file index listed below MUST belong to at least one abstraction.
After forming your initial abstractions, scan the file listing to verify no files are unassigned.
If any files are orphaned, either create a new abstraction or expand an existing one.
Do NOT skip files just because they contain only data models, configuration, or simple boilerplate —
these are architecturally significant for understanding the system's data boundaries.

GRANULARITY GUIDANCE:
- Group files that share the same design pattern and serve the same architectural role into ONE abstraction.
- Keep files that serve fundamentally different roles in SEPARATE abstractions, even if co-located in the same directory.
- Data model / schema / DTO files should be grouped with the service or component that primarily consumes them,
  NOT lumped into a catch-all "Models" or "Types" abstraction.
- If a single directory contains 20+ files, it likely spans multiple abstractions — don't force them into one.

For each abstraction, provide:
1. A concise `name`{name_lang_hint}.
2. A beginner-friendly `description` explaining what it is with a simple analogy, in around 150-250 words{desc_lang_hint}.
   Include: (a) the core problem it solves, (b) which 2-3 classes or files are most central, (c) a one-sentence note on how it connects to other parts of the system.
3. A list of relevant `file_indices` (integers) using the format `idx # path/comment`.

List of file indices and paths present in the context:
{file_listing_for_prompt}

Format the output as a YAML list of dictionaries:

```yaml
- name: |
    Query Processing{name_lang_hint}
  description: |
    Explains what the abstraction does.
    It's like a central dispatcher routing requests.{desc_lang_hint}
  file_indices:
    - 0 # path/to/file1.py
    - 3 # path/to/related.py
- name: |
    Query Optimization{name_lang_hint}
  description: |
    Another core concept, similar to a blueprint for objects.{desc_lang_hint}
  file_indices:
    - 5 # path/to/another.js
# ... up to {max_abstraction_num} abstractions
```
