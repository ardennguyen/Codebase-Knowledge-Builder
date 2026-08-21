<!-- NOTE: This template is NOT used in the current api-reference flow.
     ContextRouter routes api-reference mode to DeterministicFileMapper,
     which bypasses abstraction discovery entirely (1:1 file mapping).
     Kept for potential future use if api-reference adds a non-deterministic path. -->

Given the following API modules and their dependencies for the project `{project_name}`:

Modules (Index # Name){list_lang_note}:
{abstraction_listing}

Context about relationships and project summary:
{context}

What is the best order to present these modules in the API reference documentation?
The reader is an engineer integrating with or maintaining this system. Order for maximum "I can find and understand any API" progression.

ORDERING STRATEGY:
1. Start with core data types, shared models, and common interfaces that other modules depend on — the reader needs to understand the vocabulary before the verbs.
2. Then configuration, initialization, and client setup modules — what the developer touches first when bootstrapping.
3. Then primary domain services in dependency order (if module A calls module B, present B before A).
4. Then secondary/support services (helpers, formatters, validators) that augment the primary modules.
5. End with cross-cutting operational modules (logging, monitoring, error handling, admin utilities).

ORDERING CONSTRAINTS:
- If A depends on B (A calls B, A reads data from B, A inherits from B), prefer presenting B before A.
- Group tightly coupled modules adjacently even if they're at different layers.
- Place public-facing API surfaces before their internal implementation modules.

Output the ordered list of module indices, including the name in a comment for clarity. Use the format `idx # ModuleName`.

```yaml
- 2 # CoreDataModel
- 0 # StorageEngine
- 1 # APILayer (depends on StorageEngine)
# ...
```

Now, provide the YAML output: