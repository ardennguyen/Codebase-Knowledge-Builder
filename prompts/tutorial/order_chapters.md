Given the following project abstractions and their relationships for the project ```` {project_name} ````:

If you are going to make a tutorial for ```` {project_name} ````, what is the best order to explain these abstractions, from first to last?
Ideally, first explain those that are the most important or foundational, perhaps user-facing concepts or entry points. Then move to more detailed, lower-level implementation details or supporting concepts.

ORDERING CONSTRAINTS:
- If A depends on B (A calls B, A reads data from B, A inherits from B), prefer explaining B before A.
- Start with what the user "touches first" (entry points, configuration, core data models).
- End with cross-cutting or analytical components (logging, monitoring, reporting).

Output the ordered list of abstraction indices, including the name in a comment for clarity. Use the format `idx # AbstractionName`.

Format your response as a YAML list of integers:

```yaml
- 2 # FoundationalConcept
- 0 # CoreClassA
- 1 # CoreClassB (uses CoreClassA)
- ...
```

Abstractions (Index # Name){list_lang_note}:
{abstraction_listing}

═══════════════════════════════════════════════════════
RELATIONSHIPS AND PROJECT SUMMARY — START
═══════════════════════════════════════════════════════
{context}
═══════════════════════════════════════════════════════
RELATIONSHIPS AND PROJECT SUMMARY — END
═══════════════════════════════════════════════════════

Now, provide the YAML output:
