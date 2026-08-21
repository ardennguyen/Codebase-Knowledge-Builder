For the project `{project_name}`, your task is to identify the core logical API modules or SDK namespaces from the codebase context provided below to generate a cohesive Public SDK documentation reference.

Codebase Context:
{context}

You must identify and group the files into logically distinct SDK Modules (e.g., `Authentication`, `Database Models`, `UI Event Handlers`). Do NOT do a 1:1 file mapping. Group related files into cohesive modules.

You must return a MAXIMUM of {max_abstraction_num} modules, though you should return fewer if the architecture is simple. Make sure you cover all public-facing files.

For each module, provide:
1. A concise, professional `name`.
2. A technical `description` detailing its role in the SDK.
3. A list of relevant `file_indices` (integers) corresponding to the files that make up this module. Use the format `idx # path\comment`.

List of file indices and paths:
{file_listing}

Output the result STRICTLY as a YAML list of dictionaries, like this:
```yaml
- name: CoreEngine
  description: The main event loop and lifecycle management API.
  file_indices:
    - 0 # src/main.py
    - 5 # src/engine.py
# ... up to {max_abstraction_num} modules
```