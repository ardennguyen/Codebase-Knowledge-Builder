You are organizing a documentation sidebar for the project "{project_name}".

Below are all {module_count} documented modules with their technical summaries:

{module_list}

Directory structure of the project:
{directory_tree}

Group these modules into a LOGICAL HIERARCHY for a documentation sidebar.

Rules:
- Create as many sections and sub-sections as the project needs
- Group by PURPOSE and DOMAIN, not by directory or filename
- Section names should be meaningful to developers
- Every module MUST appear in exactly one section
- Order sections from most fundamental to most specialized
- Order modules within each section logically
- For small projects (under 15 modules), 2-4 sections is fine
- For large projects (50+ modules), use nested sub-sections
{language_note}

Return ONLY valid YAML:

```yaml
sections:
  - name: "Section Name"
    modules: ["module_name_1", "module_name_2"]
  - name: "Parent Section"
    children:
      - name: "Child Section"
        modules: ["module_name_3"]
```
