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
    - `label`: A brief, technically precise label for the interaction **in just a few words**{lang_hint}.
      The label should tell an onboarding engineer what specifically flows between components and through what mechanism.
      Examples of good labels: "calls via RPC for lookup", "subscribes to config-change events", "encrypts tokens using", "delegates background tasks to"
      Examples of bad labels: "uses", "manages", "depends on" (too vague for architecture understanding)
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
    label: "calls via RPC for lookup"{lang_hint}
  - from_abstraction: 2 # AbstractionName3
    to_abstraction: 0 # AbstractionName1
    label: "injects as dependency"{lang_hint}
  # ... other relationships
```

Now, provide the YAML output:
