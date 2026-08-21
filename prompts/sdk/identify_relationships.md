Based on the following SDK modules and relevant code snippets from the project `{project_name}`:

List of Module Indices and Names{list_lang_note}:
{abstraction_listing}

Context (Modules, Descriptions, Code):
{context}

{language_instruction}Please provide:
1. A high-level technical `summary` of the project's SDK architecture in a few sentences{lang_hint}. Use markdown formatting with **bold** and *italic* text to highlight key components and integration patterns.
2. A list (`relationships`) describing the key technical interactions, dependencies, or data flows between these modules. For each relationship, specify:
    - `from_abstraction`: Index of the source module (e.g., `0 # Module1`)
    - `to_abstraction`: Index of the target module (e.g., `1 # Module2`)
    - `label`: A precise technical label for the interaction **in just a few words**{lang_hint}.
      The label should describe WHAT flows between the two (data, control, events) and through what mechanism.
      Examples of good labels: "calls via RPC for lookup", "inherits interface from", "validates tokens via", "persists entities to", "subscribes to config-change events"
      Examples of bad labels: "uses", "manages", "depends on", "related to" (too vague to be useful for SDK consumers)
    Ideally the relationship should be backed by one module directly depending on, calling, or passing parameters to another.
    Simplify the relationship list and exclude trivial or non-important interactions.

IMPORTANT: Make sure EVERY module is involved in at least ONE relationship (either as source or target). Each module index must appear at least once across all relationships.

Format the output as YAML:

```yaml
summary: |
  A concise technical summary of the SDK architecture{lang_hint}.
  Can span multiple lines with **bold** and *italic* for emphasis.
relationships:
  - from_abstraction: 0 # Module1
    to_abstraction: 1 # Module2
    label: "calls via RPC for lookup"{lang_hint}
  - from_abstraction: 2 # Module3
    to_abstraction: 0 # Module1
    label: "injects as dependency"{lang_hint}
  # ... other relationships
```

Now, provide the YAML output: