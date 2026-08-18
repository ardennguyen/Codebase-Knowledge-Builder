For the project `{project_name}`:

Codebase Context:
{context}

{language_instruction}Analyze the codebase context.
Identify the top 5-{max_abstraction_num} core architectural abstractions and components for an advanced system onboarding reference.

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
1. A precise, technically accurate `name`{name_lang_hint}.
2. A technical `description` for an experienced engineer onboarding onto this project, in around 200-300 words{desc_lang_hint}.
   Include: (a) its architectural role and WHY it exists as a separate component, (b) design patterns used and WHY they were chosen,
   (c) its key classes/interfaces with their responsibilities, (d) its critical dependencies on other components,
   (e) what would break or degrade if this component went down.
   Use professional terminology but prioritize "understanding the system" over cataloging APIs.
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
