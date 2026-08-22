"""
Reusable prompt builders for internal LLM calls (not template-driven).

These are inline prompts used by nodes that don't load from prompts/{mode}/ templates.
Organized here for maintainability and future improvement.
"""


def build_code_file_filter_prompt(project_name: str, file_listing: str) -> str:
    """Build the prompt for DeterministicFileMapper to filter non-code files.

    Used in api-reference mode to identify which files are actual code modules
    (APIs, functions, classes, business logic) vs. UI layouts, configs, assets.
    """
    return (
        f"For the project `{project_name}`, here is the list of all files in the codebase:\n\n"
        f"{file_listing}\n\n"
        f"Your task is to identify WHICH of these files are ACTUAL CODE files that contain "
        f"APIs, functions, classes, or core business logic.\n"
        f"EXCLUDE: UI layouts (like .xaml, .storyboard, .html), configuration files "
        f"(like .xml, .json, .manifest, .ini), static assets, build scripts "
        f"(like .csproj, .sln), and documentation.\n\n"
        f"Return ONLY a YAML list of the file indices that should be documented as code modules.\n\n"
        f"```yaml\n- 0\n- 1\n- 3\n```"
    )


def build_chapter_summary_prompt(chapter_num: int, abstraction_name: str, chapter_content: str, language: str = "english") -> str:
    """Build the prompt for generating a technical summary of a written chapter.

    Used after each chapter is generated to create a concise technical summary
    for cross-chapter context. The summary is fed into subsequent chapters'
    prompts so the LLM maintains coherence across the full document.

    The summary captures 4 technical dimensions with 3-5 sentences each:
    1. Component scope & responsibility
    2. Key classes/services/functions and their roles
    3. Implementation patterns & architectural decisions
    4. Inter-component interfaces & dependencies
    """
    lang_instruction = f"Write the entire summary in {language.capitalize()}. " if language.lower() != "english" else ""
    return (
        f"{lang_instruction}"
        f"Summarize the following documentation chapter as a structured technical brief. "
        f"For EACH of the 4 points below, write 3-5 concise technical sentences:\n\n"
        f"(1) **Component Scope & Responsibility**: What is the main technical domain this "
        f"chapter covers? What problems does it solve and what role does it play in the system?\n\n"
        f"(2) **Key Technical Elements**: What are the specific classes, services, functions, "
        f"data models, or protocols discussed? Name them and describe their concrete roles.\n\n"
        f"(3) **Implementation Patterns & Architecture**: What design patterns, communication "
        f"protocols, data flow strategies, error handling mechanisms, or security measures "
        f"are covered? How are they implemented?\n\n"
        f"(4) **System Integration & Dependencies**: How does this component interface with "
        f"other parts of the system? What does it consume from or provide to other components? "
        f"What are the key integration points?\n\n"
        f"---\n"
        f"Chapter {chapter_num}: {abstraction_name}\n"
        f"{chapter_content}"
    )


def build_mkdocs_config(site_name: str, nav_yaml: str) -> str:
    """Build a complete mkdocs.yml for local --mkdocs output.

    Generates a ready-to-use MkDocs Material config with:
    - Material theme with code copy buttons
    - Syntax highlighting (pymdownx.highlight + inlinehilite)
    - Mermaid diagram rendering via pymdownx.superfences custom fences
    - Navigation from the generated nav_snippet

    Users can run `mkdocs serve` or `mkdocs build` directly in the output dir.
    """
    # Extract nav items from nav_snippet (strip the "nav:" header line)
    nav_lines = nav_yaml.split("\n")
    nav_body = "\n".join(nav_lines[1:]) if nav_lines else ""

    return (
        f"site_name: '{site_name}'\n"
        f"theme:\n"
        f"  name: material\n"
        f"  features:\n"
        f"    - content.code.copy\n"
        f"    - navigation.indexes\n"
        f"  palette:\n"
        f"    - scheme: default\n"
        f"      toggle:\n"
        f"        icon: material/brightness-7\n"
        f"        name: Switch to dark mode\n"
        f"    - scheme: slate\n"
        f"      toggle:\n"
        f"        icon: material/brightness-4\n"
        f"        name: Switch to light mode\n"
        f"plugins:\n"
        f"  - search\n"
        f"  - panzoom:\n"
        f"      include_selectors:\n"
        f"        - '.mermaid'\n"
        f"markdown_extensions:\n"
        f"  - pymdownx.highlight:\n"
        f"      anchor_linenums: true\n"
        f"      use_pygments: true\n"
        f"  - pymdownx.superfences:\n"
        f"      custom_fences:\n"
        f"        - name: mermaid\n"
        f"          class: mermaid\n"
        f"          format: !!python/name:pymdownx.superfences.fence_code_format\n"
        f"  - pymdownx.inlinehilite\n"
        f"extra_css:\n"
        f"  - stylesheets/mermaid-vibrant.css\n"
        f"nav:\n"
        f"  - Home: index.md\n"
        f"{nav_body}\n"
    )


def build_mermaid_css() -> str:
    """Build CSS overrides for vibrant Mermaid diagrams in MkDocs Material.

    Material for MkDocs forcibly overrides Mermaid's %%{init}%% directives,
    so we use CSS to restore vibrant colors matching Mermaid's default theme:
    - Yellow subgraph backgrounds
    - Lavender node fills
    - Purple node strokes
    """
    return """\
/* Vibrant Mermaid diagram theme — overrides Material's muted colors */
/* Matches Mermaid's built-in 'default' theme (yellow subgraphs, lavender nodes) */

/* Subgraph/cluster backgrounds — warm yellow */
.mermaid .cluster rect {
  fill: #ffffde !important;
  stroke: #aaaa33 !important;
  stroke-width: 1px !important;
}

/* Cluster/subgraph title text */
.mermaid .cluster text {
  fill: #333 !important;
}

/* Node fills — light lavender */
.mermaid .node rect,
.mermaid .node polygon,
.mermaid .node circle {
  fill: #ECECFF !important;
  stroke: #9370DB !important;
  stroke-width: 1px !important;
}

/* Node text */
.mermaid .nodeLabel {
  color: #333 !important;
}

/* Edge label backgrounds */
.mermaid .edgeLabel {
  background-color: #e8e8e8 !important;
  color: #333 !important;
}

/* Edge lines */
.mermaid .edge-pattern-solid {
  stroke: #333 !important;
}
"""


def build_grouped_nav(sections: list, chapter_files: list, indent: int = 4) -> list[str]:
    """Recursively build MkDocs nav YAML lines from LLM section grouping.

    Handles arbitrary nesting depth via the ``children`` key.
    Each leaf module is matched against *chapter_files* by ``module_name``.
    """
    lines = []
    pad = " " * indent
    for section in sections:
        lines.append(f"{pad}- {section['name']}:")
        if "children" in section:
            lines.extend(build_grouped_nav(section["children"], chapter_files, indent + 2))
        for mod_name in section.get("modules", []):
            match = next((cf for cf in chapter_files if cf["module_name"] == mod_name), None)
            if match:
                display = mod_name.split(".")[-1] if "." in mod_name else mod_name
                lines.append(f"{pad}  - '{display}': 'api/{match['filename']}'")
    return lines


def collect_all_modules(sections: list) -> set:
    """Recursively collect all module names referenced in a sections tree."""
    result = set()
    for section in sections:
        result.update(section.get("modules", []))
        if "children" in section:
            result.update(collect_all_modules(section["children"]))
    return result
