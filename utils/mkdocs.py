"""MkDocs output generation — config, nav, index, chapters, link normalization.

Consolidates all MkDocs-related logic that was previously scattered across
nodes.py (CombineTutorial static methods) and utils/prompts.py.
"""

import os
import re
import traceback

from utils.call_llm import call_llm
from utils.output import emit, emit_raw, get
from utils.prompts import parse_yaml_response
from utils.token_utils import log_token_estimation

# ---------------------------------------------------------------------------
# MkDocs config builders (moved from utils/prompts.py)
# ---------------------------------------------------------------------------


def build_mkdocs_config(site_name: str, nav_yaml: str, include_home: bool = True, lang_code: str = "") -> str:
    """Build a complete mkdocs.yml for local --mkdocs output.

    Generates a ready-to-use MkDocs Material config with:
    - Material theme with code copy buttons
    - Syntax highlighting (pymdownx.highlight + inlinehilite)
    - Mermaid diagram rendering via custom 'mermaid-raw' class (bypasses
      Material's Mermaid color overrides so diagrams use Mermaid's default theme)
    - Panzoom plugin for interactive Mermaid diagram zoom/pan
    - Navigation from the generated nav_snippet
    - Optional theme language for UI localization (Search, Table of Contents, etc.)

    Users can run `mkdocs serve` or `mkdocs build` directly in the output dir.
    """
    # Extract nav items from nav_snippet (strip the "nav:" header line)
    nav_lines = nav_yaml.split("\n")
    nav_body = "\n".join(nav_lines[1:]) if nav_lines else ""

    # Conditional Home nav entry (CI has root index.md, local mkdocs doesn't)
    home_line = "  - Home: index.md\n" if include_home else ""

    # Optional Material theme language (e.g. "vi", "zh", "ja", "ko")
    lang_line = f"  language: {lang_code}\n" if lang_code else ""

    return (
        f"site_name: '{site_name}'\n"
        f"theme:\n"
        f"  name: material\n"
        f"{lang_line}"
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
        f"        - '.mermaid-raw'\n"
        f"markdown_extensions:\n"
        f"  - pymdownx.highlight:\n"
        f"      anchor_linenums: true\n"
        f"      use_pygments: true\n"
        f"  - pymdownx.superfences:\n"
        f"      custom_fences:\n"
        f"        - name: mermaid\n"
        f"          class: mermaid-raw\n"
        f"          format: !!python/name:pymdownx.superfences.fence_code_format\n"
        f"  - pymdownx.inlinehilite\n"
        f"extra_javascript:\n"
        f"  - https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js\n"
        f"  - javascripts/mermaid-init.js\n"
        f"nav:\n"
        f"{home_line}"
        f"{nav_body}\n"
    )


MERMAID_INIT_JS = """\
// Mermaid initialization for MkDocs Material.
//
// Material for MkDocs targets .mermaid class for its own color overrides.
// By using .mermaid-raw, diagrams render with Mermaid's default theme:
// yellow subgraph backgrounds, lavender nodes, clean rectangles.
//
// pymdownx.superfences fence_code_format wraps content as:
//   <pre class="mermaid-raw"><code>flowchart TD ...</code></pre>
// Mermaid expects the diagram text directly in the target element,
// so we unwrap the <code> child before calling mermaid.run().
(function() {
  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    try {
      // Unwrap: move <code> text content up to <pre> and remove <code>
      document.querySelectorAll('pre.mermaid-raw > code').forEach(function(code) {
        var pre = code.parentElement;
        pre.textContent = code.textContent;
      });
      mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose'
      });
      mermaid.run({ querySelector: '.mermaid-raw' }).catch(function(err) {
        console.warn('Mermaid render error:', err);
      });
    } catch (e) {
      console.warn('Mermaid init error:', e);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMermaid);
  } else {
    initMermaid();
  }
})();
"""


def build_mermaid_init_js() -> str:
    """Return the JavaScript snippet that initializes Mermaid diagrams."""
    return MERMAID_INIT_JS


def build_grouped_nav(sections: list, chapter_files: list, indent: int = 4) -> list[str]:
    """Recursively build MkDocs nav YAML lines from LLM section grouping.

    Handles arbitrary nesting depth via the ``children`` key.
    Each leaf module is matched against *chapter_files* by ``module_name``.
    Files in subdirectories are always auto-sub-grouped by their full
    directory path (deterministic, no extra LLM call). Root-level files
    remain flat. Module names inside dir sub-layers are bare (no prefix).
    """
    emit_raw("DEBUG", f"build_grouped_nav | building nav for {len(sections)} sections", dest="LOG")
    from collections import defaultdict

    lines = []
    pad = " " * indent
    for section in sections:
        lines.append(f"{pad}- {section['name']}:")
        if "children" in section:
            lines.extend(build_grouped_nav(section["children"], chapter_files, indent + 2))

        # Collect matched modules with directory info
        matched = []
        for mod_name in section.get("modules", []):
            match = next((cf for cf in chapter_files if cf["module_name"] == mod_name), None)
            if match:
                dir_path = os.path.dirname(match.get("original_path", "")) or ""
                matched.append((dir_path, mod_name, match))

        # Group by directory
        dir_groups = defaultdict(list)
        for dir_path, mod_name, match in matched:
            dir_groups[dir_path].append((mod_name, match))

        # Emit dir sub-layers for non-root dirs, flat for root files
        has_non_root = any(d for d in dir_groups)
        if has_non_root:
            for dir_path in sorted(dir_groups.keys()):
                if dir_path:
                    # Non-root: add directory sub-layer with bare module names
                    lines.append(f"{pad}  - {dir_path}:")
                    for mod_name, match in dir_groups[dir_path]:
                        lines.append(f"{pad}    - '{mod_name}': 'api/{match['filename']}'")
                else:
                    # Root files: flat (no sub-layer)
                    for mod_name, match in dir_groups[dir_path]:
                        lines.append(f"{pad}  - '{mod_name}': 'api/{match['filename']}'")
        else:
            # All root files → flat list
            for _dir_path, mod_name, match in matched:
                lines.append(f"{pad}  - '{mod_name}': 'api/{match['filename']}'")

    return lines


def collect_all_modules(sections: list) -> set:
    """Recursively collect all module names referenced in a sections tree."""
    result = set()
    for section in sections:
        result.update(section.get("modules", []))
        if "children" in section:
            result.update(collect_all_modules(section["children"]))
    return result


# ---------------------------------------------------------------------------
# Index / link normalization / output writers (moved from nodes.py CombineTutorial)
# ---------------------------------------------------------------------------


def build_index_sections(lines, sections, chapter_files, level=3):
    """Recursively build index.md sections with module tables."""
    heading = "#" * level
    for section in sections:
        lines.append(f"{heading} {section['name']}")
        lines.append("")
        if section.get("modules"):
            lines.append(f"| {get('UI_TH_CHAPTER')} | {get('UI_TH_DESCRIPTION')} |")
            lines.append("|---------|-------------|")
            for mod_name in section["modules"]:
                match = next((cf for cf in chapter_files if cf["module_name"] == mod_name), None)
                if match:
                    display = mod_name
                    # Use description, but if it's the generic mapper description, extract from content
                    desc = match["description"]
                    if desc.startswith("Internal API reference"):
                        content_lines = match["content"].strip().split("\n")
                        for cl in content_lines:
                            cs = cl.strip()
                            if cs and not cs.startswith(("---", "#", "```", "title:", "sidebar_position:")):
                                desc = cs[:120]
                                break
                    lines.append(f"| [{display}]({match['filename']}) | {desc} |")
            lines.append("")
        for child in section.get("children", []):
            build_index_sections(lines, [child], chapter_files, level + 1)


def normalize_chapter_links(chapter_files):
    """Deterministic post-processing: fix all cross-chapter markdown link targets.

    Builds a lookup from known chapter filenames, then rewrites every
    ``[text](target.md)`` link so the target is a correct relative path
    from the current chapter's directory to the target chapter.
    """
    # Build lookup: various path forms → canonical filename
    filename_lookup = {}
    ambiguous_basenames = set()
    for cf in chapter_files:
        fname = cf["filename"]  # e.g. "CoreService/AccountingService.cs.md"
        filename_lookup[fname] = fname
        basename = fname.rsplit("/", 1)[-1]
        if basename in filename_lookup and filename_lookup[basename] != fname:
            ambiguous_basenames.add(basename)
        else:
            filename_lookup[basename] = fname

    # Remove ambiguous basenames (same name in different dirs)
    for ab in ambiguous_basenames:
        filename_lookup.pop(ab, None)

    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)#]+\.md)(#[^)]*)?\)")
    fixed_count = 0

    for cf in chapter_files:
        current_dir = os.path.dirname(cf["filename"])  # e.g. "CoreService"

        def fix_link(match, _dir=current_dir):
            nonlocal fixed_count
            text, target, anchor = match.group(1), match.group(2), match.group(3) or ""
            if target.startswith(("http://", "https://")):
                return match.group(0)
            # Try resolving the target as-is (LLM copied verbatim from index)
            canonical = filename_lookup.get(target)
            if not canonical:
                # Try resolving relative to current dir
                resolved = os.path.normpath(os.path.join(_dir, target)).replace("\\", "/")
                canonical = filename_lookup.get(resolved)
            if canonical:
                correct_rel = os.path.relpath(canonical, _dir).replace("\\", "/") if _dir else canonical
                if correct_rel != target:
                    fixed_count += 1
                return f"[{text}]({correct_rel}{anchor})"
            return match.group(0)  # Unknown target — leave as-is

        cf["content"] = link_pattern.sub(fix_link, cf["content"])

    if fixed_count:
        emit_raw("DEBUG", f"LINK NORMALIZATION | fixed {fixed_count} cross-chapter links", dest="LOG")


def write_mkdocs_output(output_path, prep_res, chapter_files):
    """Write all MkDocs output: nav grouping, mkdocs.yml, index, homepage, chapters."""
    project_name = prep_res["project_name"]
    mode = prep_res["mode"]
    api_docs_path = os.path.join(output_path, "docs", "api")
    os.makedirs(api_docs_path, exist_ok=True)

    mode_labels = {
        "tutorial": get("UI_MODE_TUTORIAL"),
        "advanced": get("UI_MODE_ADVANCED"),
        "sdk": get("UI_MODE_SDK"),
        "api-reference": get("UI_MODE_API_REF"),
    }
    site_title = f"{project_name} — {mode_labels.get(mode, 'Documentation')}"
    emit("COMBINE_FORMAT_MKDOCS", mode=mode_labels.get(mode, "Documentation"))
    emit("COMBINE_CHAPTER_COUNT", count=len(chapter_files))

    # --- LLM-Assisted Nav Grouping (api-reference only, 6+ modules) ---
    sections = None
    emit_raw("DEBUG", f"NAV GROUPING CHECK | mode={mode} | module_count={len(chapter_files)} | threshold=6", dest="LOG")
    if mode == "api-reference" and len(chapter_files) > 5:
        try:
            chapter_summaries = prep_res.get("chapter_summaries", [])
            module_entries = []
            for i, cf in enumerate(chapter_files):
                summary = chapter_summaries[i] if i < len(chapter_summaries) and chapter_summaries[i] else cf["description"]
                module_entries.append(f"- {cf['module_name']}: {summary}")
            module_list = "\n".join(module_entries)

            # Load grouping prompt template
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "common", "group_modules.md")
            with open(prompt_path, encoding="utf-8-sig") as f:
                group_template = f.read()

            language = prep_res.get("language", "english")
            language_note = f"Section names MUST be in {language}." if language.lower() != "english" else ""

            group_prompt = group_template.format(
                project_name=project_name,
                module_count=len(chapter_files),
                module_list=module_list,
                directory_tree=prep_res.get("directory_tree", "N/A"),
                language_note=language_note,
            )

            emit("LLM_CALL_GROUPING", count=len(chapter_files))

            log_token_estimation("NavGrouping", group_prompt, prep_res.get("max_tokens", 100000))
            group_response = call_llm(group_prompt, use_cache=prep_res.get("use_cache", True), thinking_level=prep_res.get("thinking_level"))
            parsed = parse_yaml_response(group_response)
            sections = parsed.get("sections", parsed) if isinstance(parsed, dict) else None

            if sections:
                # Validate: ensure all modules are covered
                grouped_modules = collect_all_modules(sections)
                ungrouped = [cf["module_name"] for cf in chapter_files if cf["module_name"] not in grouped_modules]
                if ungrouped:
                    sections.append({"name": get("UI_OTHER"), "modules": ungrouped})

                nav_lines = build_grouped_nav(sections, chapter_files, indent=4)
                nav_lines.insert(0, "    - api/index.md")
                nav_label = mode_labels.get(mode, "Documentation")
                nav_snippet = f"nav:\n  - {nav_label}:\n" + "\n".join(nav_lines)
                emit("DONE_GROUPING", count=len(sections))
            else:
                emit("GROUP_EMPTY_FALLBACK")
                nav_snippet = prep_res["nav_snippet"]

        except Exception as e:
            emit("GROUP_ERROR_FALLBACK", error=e)
            emit_raw("ERROR", f"LLM grouping failed: {e}\n{traceback.format_exc()}", dest="LOG")
            nav_snippet = prep_res["nav_snippet"]
            sections = None
    else:
        nav_snippet = prep_res["nav_snippet"]

    emit_raw(
        "DEBUG",
        f"NAV SNIPPET FINAL | grouped={sections is not None} | nav_snippet_lines={nav_snippet.count(chr(10)) + 1}",
        dest="LOG",
    )
    emit_raw("DEBUG", f"NAV SNIPPET CONTENT:\n{nav_snippet}", dest="LOG")
    if sections:
        emit("COMBINE_NAV_GROUPED", count=len(sections))
    else:
        emit("COMBINE_NAV_FLAT")

    # --- Generate mkdocs.yml ---
    lang_code_map = {
        "vietnamese": "vi",
        "chinese": "zh",
        "japanese": "ja",
        "korean": "ko",
        "french": "fr",
        "spanish": "es",
        "german": "de",
        "portuguese": "pt",
        "russian": "ru",
        "thai": "th",
        "indonesian": "id",
        "arabic": "ar",
    }
    language = prep_res.get("language", "english")
    lang_code = lang_code_map.get(language.lower(), "")
    mkdocs_config = build_mkdocs_config(site_title, nav_snippet, include_home=True, lang_code=lang_code)
    mkdocs_filepath = os.path.join(output_path, "mkdocs.yml")
    with open(mkdocs_filepath, "w", encoding="utf-8") as f:
        f.write(mkdocs_config)
    emit("FILE_WROTE", path=mkdocs_filepath)

    # --- Generate javascripts/mermaid-init.js ---
    js_dir = os.path.join(output_path, "docs", "javascripts")
    os.makedirs(js_dir, exist_ok=True)
    js_filepath = os.path.join(js_dir, "mermaid-init.js")
    with open(js_filepath, "w", encoding="utf-8") as f:
        f.write(build_mermaid_init_js())
    emit("FILE_WROTE", path=js_filepath)

    # --- Generate docs/index.md — homepage redirect to api/ ---
    mode_label = mode_labels.get(mode, "Documentation")
    home_index_path = os.path.join(output_path, "docs", "index.md")
    home_content = f'# {project_name}\n\n<meta http-equiv="refresh" content="0; url=api/">\n\n[→ {mode_label}](api/index.md)\n'
    with open(home_index_path, "w", encoding="utf-8") as f:
        f.write(home_content)
    emit("FILE_WROTE", path=home_index_path)

    # --- Generate docs/api/index.md — section landing page ---
    if sections:
        chapter_index_label = get("UI_CHAPTER_INDEX")
        chapters_label = get("UI_CHAPTERS")
        index_lines = [
            f"# {project_name} — {mode_label}",
            "",
            f"{mode_label} — **{project_name}** — **{len(chapter_files)}** {chapters_label}.",
            "",
            f"## {chapter_index_label}",
            "",
        ]
        build_index_sections(index_lines, sections, chapter_files)
        index_content = "\n".join(index_lines)
    else:
        # Build a rich flat index with module listing table
        chapter_summaries = prep_res.get("chapter_summaries", [])
        chapter_index_label = get("UI_CHAPTER_INDEX")
        chapters_label = get("UI_CHAPTERS")
        th_chapter = get("UI_TH_CHAPTER")
        th_description = get("UI_TH_DESCRIPTION")
        index_lines = [
            f"# {project_name} — {mode_label}",
            "",
            f"{mode_label} — **{project_name}** — **{len(chapter_files)}** {chapters_label}.",
            "",
            f"## {chapter_index_label}",
            "",
            f"| {th_chapter} | {th_description} |",
            "|---------|-------------|",
        ]
        for i, cf in enumerate(chapter_files):
            dir_path = os.path.dirname(cf.get("original_path", "")) or ""
            display = f"{dir_path}/{cf['module_name']}" if dir_path else cf["module_name"]
            summary = chapter_summaries[i] if i < len(chapter_summaries) and chapter_summaries[i] else cf["description"]
            # Truncate and sanitize for table cell (replace pipes and newlines)
            summary = summary.replace("|", "—").replace("\n", " ").strip()
            if len(summary) > 200:
                summary = summary[:197] + "..."
            index_lines.append(f"| [{display}]({cf['filename']}) | {summary} |")
        index_lines.append("")
        index_content = "\n".join(index_lines)
    api_index_filepath = os.path.join(api_docs_path, "index.md")
    with open(api_index_filepath, "w", encoding="utf-8") as f:
        f.write(index_content)
    emit("FILE_WROTE", path=api_index_filepath)

    # --- Write nav_snippet.yml ---
    nav_filepath = os.path.join(output_path, "docs", "nav_snippet.yml")
    with open(nav_filepath, "w", encoding="utf-8") as f:
        f.write(nav_snippet)
    emit("FILE_WROTE", path=nav_filepath)

    # --- Normalize cross-chapter links ---
    normalize_chapter_links(chapter_files)

    # --- Write chapter files ---
    for chapter_info in chapter_files:
        chapter_filepath = os.path.join(api_docs_path, chapter_info["filename"])
        os.makedirs(os.path.dirname(chapter_filepath), exist_ok=True)
        with open(chapter_filepath, "w", encoding="utf-8") as f:
            f.write(chapter_info["content"])
        emit("FILE_WROTE", path=chapter_filepath)


def write_standalone_output(output_path, prep_res, chapter_files, ui):
    """Write standalone (non-MkDocs) output: index.md, chapters, full_content.md."""
    index_content = prep_res["index_content"]
    emit("COMBINE_FORMAT_STANDALONE")
    emit("COMBINE_CHAPTER_COUNT", count=len(chapter_files))

    # Write index.md
    index_filepath = os.path.join(output_path, "index.md")
    with open(index_filepath, "w", encoding="utf-8") as f:
        f.write(index_content)
    emit("FILE_WROTE", path=index_filepath)

    # Write chapter files
    for chapter_info in chapter_files:
        chapter_filepath = os.path.join(output_path, chapter_info["filename"])
        with open(chapter_filepath, "w", encoding="utf-8") as f:
            f.write(chapter_info["content"])
        emit("FILE_WROTE", path=chapter_filepath)

    # Create full_content.md
    toc_lines = [f"# {ui['toc']}\n"]
    full_content_lines = []

    for i, chapter_info in enumerate(chapter_files):
        content = chapter_info["content"]
        title_line = content.split("\n", 1)[0]
        if title_line.startswith("# "):
            title = title_line[2:].strip()
        else:
            title = f"{ui['chapter']} {i + 1}"

        toc_lines.append(f"- [{title}](#chapter-{i + 1})")
        full_content_lines.append(f'<a id="chapter-{i + 1}"></a>\n')
        full_content_lines.append(content)
        full_content_lines.append("\n---\n")

    full_content = "\n".join(toc_lines) + "\n\n" + "\n".join(full_content_lines)
    full_content_filepath = os.path.join(output_path, "full_content.md")
    with open(full_content_filepath, "w", encoding="utf-8") as f:
        f.write(full_content)
    emit("FILE_WROTE", path=full_content_filepath)
