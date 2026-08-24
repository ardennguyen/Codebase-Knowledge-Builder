For the project `{project_name}`, your task is to identify the core logical SDK modules or namespaces from the codebase context provided below to generate a cohesive Public SDK documentation reference.

Codebase Context:
{context}

Full Project Directory Structure:
{directory_tree}

{language_instruction}You must identify and group the files into logically distinct SDK Modules (e.g., `Authentication`, `Database Models`, `UI Event Handlers`). Do NOT do a 1:1 file mapping. Group related files into cohesive modules that a developer would naturally look for when integrating this SDK.

COVERAGE RULE: Every file index listed below MUST belong to at least one SDK module.
After forming your initial modules, scan the file listing to verify no files are unassigned.
If any files are orphaned, either create a new module or expand an existing one.
Do NOT skip files just because they contain only data models, configuration, or simple boilerplate —
these define the SDK's data contracts and configuration surface.

GRANULARITY GUIDANCE:
- Group files that serve the same developer-facing functionality into ONE module (e.g., all authentication-related files into an "Authentication" module).
- Keep files that serve fundamentally different purposes in SEPARATE modules, even if co-located in the same directory.
- Data model / schema / DTO files should be grouped with the SDK module that primarily exposes them, NOT lumped into a catch-all "Models" or "Types" module.
- If a single module would expose more than 15 public classes, consider splitting it into more focused sub-modules.

You must return a MAXIMUM of {max_abstraction_num} modules, though you should return fewer if the architecture is simple.

For each module, provide:
1. A concise, professional `name`{name_lang_hint}.
2. A technical `description` of 100-250 words detailing its role in the SDK{desc_lang_hint}.
   Include: (a) what capability this module gives the SDK consumer,
   (b) key public classes/methods and their purpose,
   (c) how it relates to other modules in the SDK.
3. A list of relevant `file_indices` (integers) corresponding to the files that make up this module. Use the format `idx # path/comment`.

Output the result STRICTLY as a YAML list of dictionaries, like this:
```yaml
- name: |
    CoreEngine{name_lang_hint}
  description: |
    The main event loop and lifecycle management API. Provides the Engine class for initialization and the EventBus for inter-component communication. Used as the entry point by all other SDK modules.{desc_lang_hint}
  file_indices:
    - 0 # src/main.py
    - 5 # src/engine.py
# ... up to {max_abstraction_num} modules
```