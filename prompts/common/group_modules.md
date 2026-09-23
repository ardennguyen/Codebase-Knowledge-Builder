You are organizing a documentation sidebar for the project "{project_name}".

Group the modules listed below into a LOGICAL HIERARCHY for a documentation sidebar, write a short description of every module, and list the direct dependencies between the modules.

Rules for sections:
- Create as many sections and sub-sections as the project needs
- Group by PURPOSE and DOMAIN, not by directory or filename
- Section names should be meaningful to developers
- Every module MUST appear in exactly one section
- Order sections from most fundamental to most specialized
- Order modules within each section logically
- For small projects (under 15 modules), 2-4 sections is fine
- For large projects (50+ modules), use nested sub-sections

Rules for descriptions:
- One entry for EVERY module, keyed by its EXACT module name from the list
- 1-2 complete sentences, at most 40 words: what the module is responsible for and its single most important mechanism, entry point or design decision
- Start with the substance. No preamble ("Here is..."), no headings, no bullet points, no labels such as "(1)" or "Scope:"
- Plain prose; wrap identifiers (functions, classes, files) in backticks

Rules for dependencies:
- For each module, list the OTHER modules from the list that it directly uses: imports, calls, instantiates, or reads configuration or data from. Base this on the module summaries
- Use EXACT module names from the list. Never list a module as its own dependency, and never name anything that is not in the list
- Leave out modules that use no other listed module
{language_note}

Return ONLY valid YAML (descriptions as `>-` folded blocks, so quotes and colons inside them are safe):

```yaml
sections:
  - name: "Section Name"
    modules: ["module_name_1", "module_name_2"]
  - name: "Parent Section"
    children:
      - name: "Child Section"
        modules: ["module_name_3"]
descriptions:
  "module_name_1": >-
    Loads and validates the project settings and exposes them through `get_config()`.
  "module_name_2": >-
    One or two sentences about module_name_2.
  "module_name_3": >-
    One or two sentences about module_name_3.
dependencies:
  "module_name_1": ["module_name_2"]
  "module_name_3": ["module_name_1", "module_name_2"]
```

Directory structure of the project:
{directory_tree}

═══════════════════════════════════════════════════════
MODULE LIST ({module_count} modules) — START
═══════════════════════════════════════════════════════
{module_list}
═══════════════════════════════════════════════════════
MODULE LIST — END
═══════════════════════════════════════════════════════

Now, provide the YAML output:
