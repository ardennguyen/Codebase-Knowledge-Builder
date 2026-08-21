Given the following API modules and their dependencies for the project `{project_name}`:

Modules (Index # Name){list_lang_note}:
{abstraction_listing}

Context about relationships and project summary:
{context}

What is the best order to list these modules in the API documentation?
Start with root/core modules that have no dependencies, then move to leaf modules that depend on them.

Output the ordered list of module indices, including the name in a comment for clarity. Use the format `idx # ModuleName`.

```yaml
- 2 # CoreDataModel
- 0 # StorageEngine
- 1 # APILayer
# ...
```