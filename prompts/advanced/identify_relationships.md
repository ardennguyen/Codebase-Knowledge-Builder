Based on the following abstractions and relevant code snippets from the project `{project_name}`:

List of Abstraction Indices and Names{list_lang_note}:
{abstraction_listing}

Context (Abstractions, Descriptions, Code):
{context}

{language_instruction}Please provide:
1. A high-level technical `summary` of the project's architecture, key technologies, and design philosophy in a few sentences{lang_hint}. Use markdown formatting with **bold** and *italic* text to highlight critical architectural components.
2. A list (`relationships`) describing the key technical interactions, dependencies, or data flows between these abstractions. For each relationship, specify:
    - `from_abstraction`: Index of the source abstraction (e.g., `0 # AbstractionName1`)
    - `to_abstraction`: Index of the target abstraction (e.g., `1 # AbstractionName2`)
    - `label`: A brief, technically precise label for the interaction **in just a few words**{lang_hint} (e.g., "Instantiates", "Implements", "Passes AST to", "Observes").
    Ideally the relationship should be backed by one abstraction directly depending on, calling, or passing parameters to another.
    Exclude trivial interactions.

IMPORTANT: Make sure EVERY abstraction is involved in at least ONE relationship (either as source or target). Each abstraction index must appear at least once across all relationships.

Format the output as YAML:

```yaml
summary: |
  A concise technical summary of the project's architecture{lang_hint}.
  Can span multiple lines with **bold** and *italic* for emphasis.
relationships:
  - from_abstraction: 0 # AbstractionName1
    to_abstraction: 1 # AbstractionName2
    label: "Instantiates"{lang_hint}
  - from_abstraction: 2 # AbstractionName3
    to_abstraction: 0 # AbstractionName1
    label: "Injects dependency"{lang_hint}
  # ... other relationships
```

Now, provide the YAML output:
