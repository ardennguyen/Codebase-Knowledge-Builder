You are organizing a documentation sidebar for the project "{project_name}".

Group the modules listed below into a LOGICAL HIERARCHY for a documentation sidebar, list the direct dependencies between the modules, put the sections in reading order, and write a short description of every module.
The reader is an engineer integrating with or maintaining this system who reads the sidebar from top to bottom. Order for maximum "I can find and understand any API" progression.

Rules for dependencies (work these out first: the grouping and the reading order build on them):
- For each module, list the OTHER modules from the list that it directly uses: imports, calls, instantiates, or reads configuration or data from. Base this on the module summaries
- Use EXACT module names from the list. Never list a module as its own dependency, and never name anything that is not in the list
- Leave out modules that use no other listed module

Rules for sections:
- Create as many sections and sub-sections as the project needs
- Group by PURPOSE and DOMAIN, not by directory or filename
- Keep tightly coupled modules in the same section
- Section names should be meaningful to developers
- Every module MUST appear in exactly one section, under its EXACT module name from the list
- For small projects (under 15 modules), 2-4 sections is fine
- For large projects (50+ modules), use nested sub-sections

Rules for reading order (give EVERY section and sub-section a role; the sidebar presents the roles in this order):
1. types: core data types, shared models, schemas and common interfaces that other modules depend on (the vocabulary before the verbs)
2. setup: entry points, configuration, initialization and client setup (what a developer runs, calls or configures first)
3. core: the primary domain services and pipeline stages
4. support: secondary services that augment the core modules (helpers, formatters, validators)
5. operational: cross-cutting operational modules (logging and console output, monitoring, telemetry, localization, error handling, admin utilities)
- A section that holds the program's entry point (CLI or application main, bootstrap, or the package index that exports the public API) is setup
- Logging, console output, localization and error helpers are operational even when every module uses them; types is only for data models, schemas and interfaces
- Provider or adapter modules behind a facade take the role of that facade
- Any other section that mixes roles takes the role of most of its modules
- Sections with the same role: in dependency order (if a module in A uses a module in B, B comes first). Only when neither uses the other, or both use each other, put public-facing surfaces before internal implementation
- Order the sub-sections of a section and the modules inside a section by the same strategy. The sidebar shows the modules of one directory together, at the position of the first one you list, so list the most important module of each directory first
- Do not order sections alphabetically, by directory, or by the order of the list below
- Write each role unquoted, exactly as one of the five English words above (for example `role: core`), in every language

Rules for descriptions:
- One entry for EVERY module, keyed by its EXACT module name from the list
- 1-2 complete sentences, at most 40 words: what the module is responsible for and its single most important mechanism, entry point or design decision
- Start with the substance. No preamble ("Here is..."), no headings, no bullet points, no labels such as "(1)" or "Scope:"
- Plain prose; wrap identifiers (functions, classes, files) in backticks
{language_note}

Return ONLY valid YAML, with the keys in this order (descriptions as `>-` folded blocks, so quotes and colons inside them are safe):

```yaml
dependencies:
  "module_name_1": ["module_name_2"]
  "module_name_3": ["module_name_1", "module_name_2"]
sections:
  - name: "Section Name"
    role: setup
    modules: ["module_name_2", "module_name_1"]
  - name: "Parent Section"
    role: core
    children:
      - name: "Child Section"
        role: core
        modules: ["module_name_3"]
descriptions:
  "module_name_1": >-
    Loads and validates the project settings and exposes them through `get_config()`.
  "module_name_2": >-
    One or two sentences about module_name_2.
  "module_name_3": >-
    One or two sentences about module_name_3.
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
