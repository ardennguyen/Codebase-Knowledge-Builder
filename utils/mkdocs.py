"""MkDocs output generation — config, nav, index, chapters, link normalization.

Consolidates all MkDocs-related logic that was previously scattered across
nodes.py (CombineTutorial static methods) and utils/prompts.py.
"""

import json
import os
import posixpath
import re
import textwrap
import time
import traceback
from collections import Counter, defaultdict

import yaml

from utils.call_llm import call_llm
from utils.chapter_check import USED_BY_MARKER, markup_problems, markup_verdicts, parse_page, run_chapter_check
from utils.llm_common import LLMRefusalError
from utils.output import emit, emit_raw, get
from utils.prompts import parse_grouping_response
from utils.token_utils import log_token_estimation

# ---------------------------------------------------------------------------
# MkDocs config builders (moved from utils/prompts.py)
# ---------------------------------------------------------------------------


def yaml_str(value) -> str:
    """Quote a scalar for hand-built YAML (nav labels, section names, titles).

    JSON string literals are valid YAML double-quoted scalars, so names containing
    apostrophes, colons, brackets or a leading @ never break mkdocs.yml or frontmatter.
    """
    return json.dumps(str(value).strip(), ensure_ascii=False)


def build_mkdocs_config(site_name: str, nav_yaml: str, include_home: bool = True, lang_code: str = "") -> str:
    """Build a complete mkdocs.yml for local --mkdocs output.

    Generates a ready-to-use MkDocs Material config with:
    - Material theme with code copy buttons
    - Syntax highlighting (pymdownx.highlight + inlinehilite)
    - Mermaid diagram rendering via custom 'mermaid-raw' class (bypasses
      Material's Mermaid color overrides so diagrams use Mermaid's default theme).
      The fence renders as <div class="mermaid-raw"> because panzoom only activates on DIV/IMG.
    - Panzoom plugin for interactive Mermaid diagram zoom/pan ('.mermaid' excluded: the
      plugin's default '.mermaid' selector also matches 'mermaid-raw' and double-wraps diagrams),
      with a full-screen button for wide diagrams such as the api/index.md module graph
    - Navigation from the generated nav_snippet
    - Optional theme language for UI localization (Search, Table of Contents, etc.)

    Users can run `mkdocs serve` or `mkdocs build` directly in the output dir.
    Keep in sync with MKDOCS_YML in .github/ci_mkdocs_config.py.
    """
    # Extract nav items from nav_snippet (strip the "nav:" header line)
    nav_lines = nav_yaml.split("\n")
    nav_body = "\n".join(nav_lines[1:]) if nav_lines else ""

    # Optional Home nav entry (write_mkdocs_output always writes docs/index.md and passes include_home=True)
    home_line = f"  - {yaml_str(get('UI_HOME'))}: index.md\n" if include_home else ""

    # Optional Material theme language (e.g. "vi", "zh", "ja", "ko")
    lang_line = f"  language: {lang_code}\n" if lang_code else ""

    return (
        f"site_name: {yaml_str(site_name)}\n"
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
        f"      full_screen: true\n"
        f"      include_selectors:\n"
        f"        - '.mermaid-raw'\n"
        f"      exclude_selectors:\n"
        f"        - '.mermaid'\n"
        f"markdown_extensions:\n"
        f"  - pymdownx.highlight:\n"
        f"      anchor_linenums: true\n"
        f"      use_pygments: true\n"
        f"  - pymdownx.superfences:\n"
        f"      custom_fences:\n"
        f"        - name: mermaid\n"
        f"          class: mermaid-raw\n"
        f"          format: !!python/name:pymdownx.superfences.fence_div_format\n"
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
// pymdownx.superfences fence_div_format emits the diagram source directly as:
//   <div class="mermaid-raw">flowchart TD ...</div>
// which is what mermaid.run() reads and what the panzoom plugin activates on (DIV/IMG only).
//
// securityLevel stays at Mermaid's default ('strict'): diagram source is LLM-generated.
//
// Mermaid's default theme draws edges in dark gray, which disappear on Material's
// dark (slate) palette, so diagrams get a light card there.
(function() {
  var style = document.createElement('style');
  style.textContent = '[data-md-color-scheme="slate"] .mermaid-raw { background-color: #fff; border-radius: .2rem; }';
  document.head.appendChild(style);

  function initMermaid() {
    if (typeof mermaid === 'undefined') return;
    try {
      mermaid.initialize({
        startOnLoad: false,
        theme: 'default'
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


def site_renderer():
    """``render(markdown) -> html`` with the Markdown pipeline of the generated site, for the chapter check: MkDocs'
    built-in ``toc``, ``tables`` and ``fenced_code`` plus the ``markdown_extensions`` read from
    ``build_mkdocs_config`` itself (its ``!!python/name`` tag resolved like MkDocs does), so the check never reads a
    page differently from the site. None when Markdown or the extensions are not installed (they come with MkDocs)."""
    try:
        import markdown

        config = yaml.load(build_mkdocs_config("", "nav:"), Loader=yaml.Loader)  # our own config
        names, options = ["toc", "tables", "fenced_code"], {}
        for entry in config["markdown_extensions"]:
            name, settings = next(iter(entry.items())) if isinstance(entry, dict) else (entry, None)
            if name not in names:
                names.append(name)
            if settings:
                options[name] = settings
        renderer = markdown.Markdown(extensions=names, extension_configs=options)
    except Exception as e:
        emit("CHAPTER_CHECK_NO_RENDERER", error=f"{type(e).__name__}: {e}")
        return None

    def render(text: str) -> str:
        return renderer.reset().convert(text)

    return render


# ---------------------------------------------------------------------------
# Chapter filenames and summary text helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^-{3}[ \t]*\n(.*?\n)(?:\.{3}|-{3})[ \t]*\n", re.DOTALL)  # same block MkDocs' meta parser reads
_SUMMARY_HEADER_RE = re.compile(r"^.+ \d+ — .+:$")
# "(1) **Label**:", "**(1) Label:**", "### (1) Label:", "1. Label:" — ASCII or full-width colon (CJK summaries)
_SUMMARY_LABEL_RE = re.compile(r"^[\s#>*_]*\(?1[.)]\W{0,3}[^:\uff1a\n]{1,80}[:\uff1a]\**\s*")
_POINT_MARKER_RE = re.compile(r"^[\s#>*_]*\(?1[.)][\s*_]*")  # the bare "(1)" / "### (1)" / "**1." marker
_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]|])")
# A numbered brief point at line start: "(1)", "### (1)", "**(1)" (what the summary prompt asks for), else "1." / "1)"
_POINT_PAREN_RE = re.compile(r"(?m)^[ \t#>*_]*\(([1-4])\)")
_POINT_PLAIN_RE = re.compile(r"(?m)^[ \t#>*_]*([1-4])[.)]\s")
# Sentence ends: ". ! ?" before whitespace, CJK "\u3002\uff01\uff1f" with or without it (CJK text has no spaces)
_CJK_STOPS = ("\u3002", "\uff01", "\uff1f")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+|(?<=[\u3002\uff01\uff1f])\s*")
_ABBREVIATIONS = ("e.g.", "i.e.", "vs.", "etc.", "cf.", "approx.", "incl.", "resp.", "no.", "fig.")
_CODE_SPAN_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
_ENTRY_NODE_CLASSDEF = "    classDef entryNode stroke:#d33,stroke-width:3px,fill:#fff5f5"
_MODULE_GRAPH_MAX_MODULES = 80  # beyond this a module-level graph is unreadable; the section map still shows


def build_chapter_filenames(chapter_order: list, abstractions: list, is_mkdocs: bool) -> dict:
    """Map each valid position in *chapter_order* to its chapter filename.

    Shared by WriteChapters (link targets given to the LLM) and CombineTutorial (files written)
    so both always agree. --mkdocs: the mirrored source path when the abstraction has an
    ``original_path`` (api-reference), else the sanitized name; standalone: ``NN_`` prefix.
    Names that collide case-insensitively with another chapter or with the generated
    ``index.md`` get a numeric suffix, so no chapter can overwrite another page. MkDocs builds
    ``README.md`` as its directory's index page, so it counts as ``index.md`` of that directory.
    """

    def page_key(filename):
        directory, basename = posixpath.split(filename.lower())
        return posixpath.join(directory, "index.md") if basename == "readme.md" else filename.lower()

    filenames = {}
    used = {"index.md"}
    for i, abstraction_index in enumerate(chapter_order):
        if not 0 <= abstraction_index < len(abstractions):
            continue
        abstraction = abstractions[abstraction_index]
        if is_mkdocs and abstraction.get("original_path"):
            base = abstraction["original_path"].replace(os.sep, "/")
        else:
            chapter_name = abstraction["name"].replace("\n", " ").strip()
            safe_name = "".join(c if c.isalnum() else "_" for c in chapter_name).lower()
            base = safe_name if is_mkdocs else f"{i + 1:02d}_{safe_name}"
        filename, suffix = f"{base}.md", 2
        while page_key(filename) in used:
            filename, suffix = f"{base}_{suffix}.md", suffix + 1
        used.add(page_key(filename))
        filenames[i] = filename
    return filenames


def split_frontmatter(text: str) -> tuple[str, bool]:
    """Split a leading YAML frontmatter block off *text*, recognized the way MkDocs does.

    Returns ``(body, found)``. Only a block that parses as a YAML mapping counts, so a chapter that merely
    opens with a ``---`` horizontal rule keeps all of its content.
    """
    match = _FRONTMATTER_RE.match(text)
    if match:
        try:
            if isinstance(yaml.safe_load(match.group(1)), dict):
                return text[match.end() :].strip(), True
        except Exception:  # like MkDocs: YAMLError, or e.g. ValueError from an impossible date (2024-02-30)
            pass
    return text, False


def strip_summary_header(summary: str) -> str:
    """Drop the ``<Chapter> N — name:`` first line that WriteChapters puts on every chapter summary."""
    first, sep, rest = summary.partition("\n")
    if sep and _SUMMARY_HEADER_RE.match(first.strip()):
        return rest.strip()
    return summary.strip()


def _sentences(text: str):
    """Yield the sentences of *text*; an abbreviation such as "e.g." or "vs." does not end one."""
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        piece = text[start : match.start()]
        if not piece or _ends_with_abbreviation(piece):
            continue
        yield piece
        start = match.end()
    if text[start:]:
        yield text[start:]


def _ends_with_abbreviation(piece: str) -> bool:
    """True when *piece* ends with a whole-word abbreviation ("… e.g." but not "… piano.")."""
    lower = piece.lower()
    for abbreviation in _ABBREVIATIONS:
        if lower.endswith(abbreviation):
            before = lower[: -len(abbreviation)][-1:]
            if not before or not before.isalnum():
                return True
    return False


def _is_prose(text: str) -> bool:
    """True when *text* holds sentence punctuation, i.e. is prose rather than a bare label line."""
    stripped = text.rstrip("*_ ")
    return any(mark in text for mark in (". ", "! ", "? ", *_CJK_STOPS)) or stripped.endswith((".", "!", "?"))


def clip_sentences(text: str, limit: int) -> str:
    """Collapse whitespace and keep whole sentences up to *limit* characters.

    A first sentence longer than *limit* is cut at a word boundary (for text without spaces, such as
    CJK, at *limit*) and ends with "…" (closing a code span it would otherwise leave open), so a cell
    never stops mid-word or with a dangling backtick.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    clipped = ""
    for sentence in _sentences(text):
        separator = "" if not clipped or clipped.endswith(_CJK_STOPS) else " "
        candidate = f"{clipped}{separator}{sentence}"
        if len(candidate) > limit:
            break
        clipped = candidate
    if not clipped:
        clipped = text[:limit].rsplit(" ", 1)[0].rstrip(",;:—\u2013- ")
        if clipped.count("`") % 2:
            clipped += "`"
        clipped += "…"
    return clipped


def table_cell_text(text: str) -> str:
    """Escape ``|`` for a Markdown table cell, except inside code spans (the tables extension already
    ignores pipes there, so ``str | None`` stays intact)."""
    parts, position = [], 0
    for match in _CODE_SPAN_RE.finditer(text):
        parts.append(text[position : match.start()].replace("|", "\\|"))
        parts.append(match.group(0))
        position = match.end()
    parts.append(text[position:].replace("|", "\\|"))
    return "".join(parts)


def summary_description(summary: str, limit: int = 300) -> str:
    """Fallback table-cell description from a chapter summary (when the grouping reply has none).

    Summaries are 4-point briefs, often wrapped in a preamble ("Here is a structured technical brief
    ...:") with the points as headings ("### (1) Component Scope & Responsibility") or inline labels
    ("(1) **Component Scope & Responsibility**: ..."). This keeps only point (1) without its marker and
    label and returns whole sentences up to *limit* characters, made safe for a table cell.
    """
    text = strip_summary_header(summary)
    points = [m for m in _POINT_PAREN_RE.finditer(text) if m.group(1) in ("1", "2")]
    if not points:
        points = [m for m in _POINT_PLAIN_RE.finditer(text) if m.group(1) in ("1", "2")]
    if points and points[0].group(1) == "1":
        end = next((m.start() for m in points[1:] if m.group(1) == "2"), len(text))
        text = text[points[0].start() : end].strip()
        first, sep, rest = text.partition("\n")
        if _SUMMARY_LABEL_RE.match(first):
            text = _SUMMARY_LABEL_RE.sub("", text, count=1)  # inline "(1) **Label**: substance"
        elif sep and rest.strip() and not _is_prose(_POINT_MARKER_RE.sub("", first, count=1)):
            text = rest  # the first line is only the label: "### (1) Component Scope & Responsibility"
        else:
            text = _POINT_MARKER_RE.sub("", text, count=1)  # "(1) The module ..." without a label
    else:
        first, sep, rest = text.partition("\n")
        if sep and rest.strip() and len(first) <= 120 and first.rstrip().endswith((":", "\uff1a")):
            text = rest  # a preamble line in any language: "Here is ...:", "Dưới đây là ...:"
    return table_cell_text(clip_sentences(text, limit))


def md_link_text(text: str) -> str:
    """Escape Markdown metacharacters so names like ``__init__.py`` render literally as link text."""
    return _MD_ESCAPE_RE.sub(r"\\\1", " ".join(str(text).split()))


def md_heading_text(text: str) -> str:
    """``md_link_text`` for a heading: ``#`` escaped too (a trailing one would read as the closing sequence), so a
    section named after a directory (``src/__tests__``, ``Samples/C#``) renders literally."""
    return md_link_text(text).replace("#", "\\#")


# ---------------------------------------------------------------------------
# Grouping reply extras (descriptions, dependencies) and index diagrams
# ---------------------------------------------------------------------------


def module_name_lookup(chapter_files: list) -> dict:
    """Map every name an LLM may use for a module to its ``module_name``.

    Accepts the exact ``module_name``, the ``original_path`` and, when unique, the bare basename.
    """
    lookup = {}
    basename_counts = Counter(os.path.basename(cf.get("original_path") or cf["module_name"]) for cf in chapter_files)
    for cf in chapter_files:
        name = cf["module_name"]
        lookup[name] = name
        if cf.get("original_path"):
            lookup.setdefault(cf["original_path"], name)
        basename = os.path.basename(cf.get("original_path") or name)
        if basename_counts[basename] == 1:
            lookup.setdefault(basename, name)
    return lookup


def grouping_extras(parsed, chapter_files: list) -> tuple[dict, dict]:
    """Validated ``descriptions`` and ``dependencies`` from a group_modules.md reply.

    Returns ``({module_name: description}, {module_name: [module_name, ...]})``. Unknown names, self
    dependencies, duplicates and non-string values are dropped; descriptions are cleaned for a table
    cell (whole sentences, at most 400 characters, pipes replaced).
    """
    descriptions, dependencies = {}, {}
    if not isinstance(parsed, dict):
        return descriptions, dependencies
    lookup = module_name_lookup(chapter_files)

    raw_descriptions = parsed.get("descriptions")
    if isinstance(raw_descriptions, dict):
        for key, text in raw_descriptions.items():
            name = lookup.get(str(key).strip())
            if name and isinstance(text, str) and text.strip():
                descriptions[name] = table_cell_text(clip_sentences(text, 400))

    raw_dependencies = parsed.get("dependencies")
    if isinstance(raw_dependencies, dict):
        pairs = list(raw_dependencies.items())
    elif isinstance(raw_dependencies, list):  # tolerate [{from: a, to: [b]}]
        pairs = [(item.get("from"), item.get("to")) for item in raw_dependencies if isinstance(item, dict)]
    else:
        pairs = []
    for key, targets in pairs:
        source = lookup.get(str(key).strip())
        if not source:
            continue
        if isinstance(targets, str):
            targets = [targets]
        if not isinstance(targets, list):
            continue
        resolved = dependencies.setdefault(source, [])
        for target in targets:
            name = lookup.get(str(target).strip())
            if name and name != source and name not in resolved:
                resolved.append(name)
        if not resolved:
            del dependencies[source]
    return descriptions, dependencies


def modules_with_facts(module_facts: dict, chapter_files: list) -> set:
    """``module_name`` of every chapter whose ExtractFacts run produced facts (its edges are verified, even
    when it has none); modules whose extraction failed are left out."""
    name_of = {cf["original_path"]: cf["module_name"] for cf in chapter_files if cf.get("original_path")}
    return {name_of[path] for path, entry in (module_facts or {}).items() if path in name_of and entry.get("claims") is not None}


def verified_dependencies(module_facts: dict, chapter_files: list) -> dict:
    """``{module_name: [module_name, ...]}`` from ExtractFacts' source-verified edges; ``{}`` without facts."""
    name_of = {cf["original_path"]: cf["module_name"] for cf in chapter_files if cf.get("original_path")}
    dependencies = {}
    for path, entry in (module_facts or {}).items():
        source = name_of.get(path)
        targets = [name_of[edge["module"]] for edge in entry.get("depends_on", []) if edge.get("module") in name_of]
        targets = [name for name in dict.fromkeys(targets) if name != source]
        if source and targets:
            dependencies[source] = targets
    return dependencies


def _section_members(sections: list) -> list[tuple[str, list]]:
    """``[(top-level section name, [module_name, ...])]``, children folded into their top-level section;
    a module listed in several sections belongs to the first."""
    owned = set()

    def modules_of(section):
        found = list(section.get("modules", []))
        for child in section.get("children", []):
            found += modules_of(child)
        return found

    groups = []
    for section in sections:
        members = []
        for name in modules_of(section):
            if name not in owned:
                owned.add(name)
                members.append(name)
        groups.append((section["name"], members))
    return groups


def _mermaid_label(text) -> str:
    """Text for a quoted Mermaid label, with Mermaid's special characters as entity codes.

    A label opening with a backtick starts a markdown string and breaks the whole diagram; "<...>" is
    stripped by the sanitizer and "#...;" decoded as an entity. "#" is escaped first so the other codes
    are not escaped twice. Callers add their own "<br/>" separators after escaping.
    """
    text = " ".join(str(text).split())
    for char, code in (("#", "#35;"), ('"', "#quot;"), ("`", "#96;"), ("<", "#lt;"), (">", "#gt;")):
        text = text.replace(char, code)
    return text


def build_section_map(sections: list, dependencies: dict, max_listed: int = 8) -> tuple[str, bool, bool]:
    """Mermaid source for the api/index.md architecture overview: one node per top-level nav section
    listing its modules, an arrow A --> B when a module in A uses one in B.

    Sections that other sections depend on most (2+ incoming) get the ``entryNode`` class. Returns
    ``(source, has_arrows, has_hubs)`` so the caption only explains what is drawn; ``("", False, False)``
    for fewer than two sections.
    """
    groups = _section_members(sections)
    if len(groups) < 2:
        return "", False, False
    owner = {name: index for index, (_, members) in enumerate(groups) for name in members}
    edges = sorted(
        {
            (owner[source], owner[target])
            for source, targets in dependencies.items()
            for target in targets
            if source in owner and target in owner and owner[source] != owner[target]
        }
    )
    lines = ["flowchart TD"]
    for index, (name, members) in enumerate(groups):
        listed = ", ".join(members[:max_listed])
        if len(members) > max_listed:
            listed += f", {get('UI_MORE', count=len(members) - max_listed)}"
        lines.append(f'    S{index}["{_mermaid_label(name)}<br/>{_mermaid_label(listed)}"]')
    lines.extend(f"    S{source} --> S{target}" for source, target in edges)
    incoming = Counter(target for _, target in edges)
    hubs = [f"S{index}" for index in range(len(groups)) if incoming[index] >= 2]
    if hubs:
        lines.append(_ENTRY_NODE_CLASSDEF)
        lines.append(f"    class {','.join(hubs)} entryNode")
    return "\n".join(lines), bool(edges), bool(hubs)


def build_module_graph(sections: list, dependencies: dict, chapter_files: list) -> tuple[str, int]:
    """Mermaid source for the api/index.md module dependency graph: one box per top-level nav section,
    one node per module, an arrow A --> B when module A uses module B.

    Hub modules, used by at least ``max(5, modules // 4)`` others (typically logging, config and shared
    types), would pull a fan of arrows across the whole graph. They get the ``entryNode`` class and a
    "used by N modules" label instead of their incoming arrows. Returns ``(source, hub_threshold)``;
    the threshold is 0 when no module is a hub. Returns ``("", 0)`` without dependencies or above
    ``_MODULE_GRAPH_MAX_MODULES`` modules (unreadable).
    """
    if not dependencies or len(chapter_files) > _MODULE_GRAPH_MAX_MODULES:
        return "", 0
    ids = {cf["module_name"]: f"M{index}" for index, cf in enumerate(chapter_files)}
    edges = [(source, target) for source, targets in dependencies.items() for target in targets if source in ids and target in ids]
    incoming = Counter(target for _, target in edges)
    threshold = max(5, len(chapter_files) // 4)
    hubs = {name for name in ids if incoming[name] >= threshold}

    def node(name):
        label = _mermaid_label(name)
        if name in hubs:
            label += f"<br/>{_mermaid_label(get('UI_USED_BY', count=incoming[name]))}"
        return f'{ids[name]}["{label}"]'

    lines = ["flowchart LR"]
    placed = set()
    for index, (name, members) in enumerate(_section_members(sections)):
        members = [m for m in members if m in ids]
        if not members:
            continue
        lines.append(f'    subgraph G{index}["{_mermaid_label(name)}"]')
        lines.extend(f"        {node(m)}" for m in members)
        lines.append("    end")
        placed.update(members)
    lines.extend(f"    {node(name)}" for name in ids if name not in placed)
    lines.extend(f"    {ids[source]} --> {ids[target]}" for source, target in edges if target not in hubs)
    if hubs:
        lines.append(_ENTRY_NODE_CLASSDEF)
        lines.append(f"    class {','.join(ids[name] for name in ids if name in hubs)} entryNode")
    return "\n".join(lines), (threshold if hubs else 0)


def build_hub_fan_ins(sections: list, dependencies: dict, chapter_files: list, threshold: int) -> list[tuple[str, str]]:
    """``[(hub, Mermaid source)]`` for the modules the module graph folds as hubs (used by ``threshold`` or more
    others), most used first: who uses each of them, since the graph shows only their count. One small diagram
    per hub — a box per nav section naming the modules in it that use the hub, one arrow from the box to the hub
    labelled with how many they are — readable where one arrow per user would tangle the module graph."""
    names = {cf["module_name"] for cf in chapter_files}
    edges = [(source, target) for source, targets in dependencies.items() for target in targets if source in names and target in names]
    users = defaultdict(list)
    for source, target in edges:
        users[target].append(source)
    groups = _section_members(sections)
    owner = {name: index for index, (_, members) in enumerate(groups) for name in members}
    diagrams = []
    for hub in sorted((name for name in users if len(users[name]) >= threshold), key=lambda name: (-len(users[name]), name)):
        by_section = defaultdict(list)
        for user in users[hub]:
            by_section[owner.get(user, len(groups))].append(user)
        lines = ["flowchart LR"]
        for index in sorted(by_section):
            title = groups[index][0] if index < len(groups) else get("UI_OTHER")
            members = sorted(by_section[index], key=lambda name: groups[index][1].index(name) if index < len(groups) else 0)
            lines.append(f'    S{index}["{_mermaid_label(title)}<br/>{_mermaid_label(", ".join(members))}"]')
        lines.append(f'    H["{_mermaid_label(hub)}<br/>{_mermaid_label(get("UI_USED_BY", count=len(users[hub])))}"]')
        lines.extend(f"    S{index} -->|{len(by_section[index])}| H" for index in sorted(by_section))
        lines += [_ENTRY_NODE_CLASSDEF, "    class H entryNode"]
        diagrams.append((hub, "\n".join(lines)))
    return diagrams


def build_grouped_nav(sections: list, chapter_files: list, indent: int = 4) -> list[str]:
    """Recursively build MkDocs nav YAML lines from LLM section grouping.

    Handles arbitrary nesting depth via the ``children`` key; a section lists its own
    modules first, then its children (the order of the index tables and diagrams).
    Each leaf module is matched against *chapter_files* by ``module_name``.
    Files in subdirectories are always auto-sub-grouped by their full
    directory path (deterministic, no extra LLM call), in the order the section
    first lists them. Root-level files remain flat. Module names inside dir
    sub-layers are bare (no prefix).
    """
    emit_raw("DEBUG", f"build_grouped_nav | building nav for {len(sections)} sections", dest="LOG")

    lines = []
    pad = " " * indent
    for section in sections:
        lines.append(f"{pad}- {yaml_str(section['name'])}:")

        # Group matched modules by directory, keeping the section's module order
        dir_groups = defaultdict(list)
        for mod_name in section.get("modules", []):
            match = next((cf for cf in chapter_files if cf["module_name"] == mod_name), None)
            if match:
                dir_groups[os.path.dirname(match.get("original_path") or "")].append((mod_name, match))

        # Emit dir sub-layers for non-root dirs, flat for root files
        for dir_path, members in dir_groups.items():
            item_pad = f"{pad}  "
            if dir_path:
                # Non-root: add directory sub-layer with bare module names
                lines.append(f"{pad}  - {yaml_str(dir_path)}:")
                item_pad = f"{pad}    "
            lines.extend(f"{item_pad}- {yaml_str(mod_name)}: {yaml_str('api/' + match['filename'])}" for mod_name, match in members)

        if "children" in section:
            lines.extend(build_grouped_nav(section["children"], chapter_files, indent + 2))

    return lines


def collect_all_modules(sections: list) -> set:
    """Recursively collect all module names referenced in a sections tree."""
    result = set()
    for section in sections:
        result.update(section.get("modules", []))
        if "children" in section:
            result.update(collect_all_modules(section["children"]))
    return result


def prune_sections(sections: list, chapter_files: list) -> list:
    """Resolve grouped module names (``module_name_lookup``), drop names that match no chapter, then
    drop sections left empty, and sections without a name.

    An empty section would be emitted as a null nav entry (``- "Name":``), which makes
    ``mkdocs build`` abort with "Expected nav to be a list, got None".
    """
    lookup = module_name_lookup(chapter_files)
    pruned = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("name"), str) or not section["name"].strip():
            continue  # a section without a name cannot become a nav entry: its modules go to "Other"
        names = [m.strip() for m in section.get("modules") or [] if isinstance(m, str)]
        modules = list(dict.fromkeys(lookup[name] for name in names if name in lookup))
        children = prune_sections(section.get("children") or [], chapter_files)
        if not modules and not children:
            continue
        kept = {key: value for key, value in section.items() if key != "children"}
        kept["modules"] = modules
        if children:
            kept["children"] = children
        pruned.append(kept)
    return pruned


def tree_order_key(chapter_file: dict) -> tuple:
    """Sort key for directory-tree order (root files first, then directories alphabetically), the
    order of ``build_directory_tree``; ``chapter_files`` itself is in generation order."""
    return os.path.split(chapter_file.get("original_path") or "")


def directory_sections(chapter_files: list) -> list:
    """Index sections from the directory tree — root files first, then one section per directory,
    alphabetically, each in chapter order: the directory nav's layout and order — for an api-reference index
    without an LLM grouping (it failed, or 5 modules or fewer), which keeps its section tables, section map and
    module dependency graph."""
    groups = {}
    for cf in chapter_files:
        groups.setdefault(os.path.dirname(cf.get("original_path") or ""), []).append(cf["module_name"])
    return [{"name": directory or get("UI_ROOT_FILES"), "modules": groups[directory]} for directory in sorted(groups)]


GROUPING_ATTEMPTS = 3  # like the pipeline's LLM nodes: a stream cut off upstream must not cost the grouped nav
GROUPING_WAIT = 20  # seconds between attempts


def request_grouping(prompt: str, prep_res: dict, chapter_files: list) -> tuple[dict, list]:
    """``(parsed reply, pruned sections)`` of the group_modules call, retried up to ``GROUPING_ATTEMPTS``
    times when the call fails (e.g. an upstream idle timeout on the long thinking-heavy reply), the reply does
    not parse, or it names no module of the project; the cache is read on the first attempt only. A refusal the
    provider would repeat is not retried. The last failure is raised."""
    use_cache = prep_res.get("use_cache", True)
    attempt = 1
    while True:
        try:
            response = call_llm(prompt, use_cache=use_cache and attempt == 1, thinking_level=prep_res.get("thinking_level"), step="group_modules")
            parsed = parse_grouping_response(response)
            sections = parsed.get("sections", parsed) if isinstance(parsed, dict) else None
            # Drop unknown module names and the sections they leave empty (null nav entries break mkdocs build)
            sections = prune_sections(sections, chapter_files) if isinstance(sections, list) else []
            if not sections:
                raise ValueError(get("GROUP_NO_SECTIONS"))
            return (parsed if isinstance(parsed, dict) else {}), sections
        except LLMRefusalError as e:
            if not e.retryable:
                raise
            error = e
        except Exception as e:
            error = e
        if attempt == GROUPING_ATTEMPTS:
            raise error
        emit("GROUP_RETRY", attempt=attempt, attempts=GROUPING_ATTEMPTS, error=error, wait=GROUPING_WAIT)
        time.sleep(GROUPING_WAIT)
        attempt += 1


# Reading-order roles of nav sections, in the order prompts/api-reference/order_chapters.md presents
# modules: vocabulary, what a developer touches first, the domain, its helpers, cross-cutting last
SECTION_ROLES = ("types", "setup", "core", "support", "operational")


def order_sections(sections: list, chapter_files: list) -> list:
    """Sections in reading order, as new dicts.

    Siblings are stably sorted by their ``role`` (``SECTION_ROLES`` order), so the reply's order
    decides within a role; a level where any section lacks a known role keeps the reply's order.
    Each section's modules are grouped by directory in first-appearance order, the order of the
    nav's directory sub-layers, so nav, index tables and diagrams list them the same way. Only the
    role order is enforced: the grouping reply's dependencies are inferred from summaries and too
    noisy to reorder the model's choices within a role.
    """
    rank = {role: index for index, role in enumerate(SECTION_ROLES)}
    dir_of = {cf["module_name"]: os.path.dirname(cf.get("original_path") or "") for cf in chapter_files}

    def role_rank(section):
        return rank.get(str(section.get("role", "")).strip().lower())

    def ordered(level):
        level = [dict(section) for section in level]
        for section in level:
            modules = section.get("modules") or []
            dirs = list(dict.fromkeys(dir_of.get(name, "") for name in modules))
            section["modules"] = [name for dir_path in dirs for name in modules if dir_of.get(name, "") == dir_path]
            if section.get("children"):
                section["children"] = ordered(section["children"])
        if all(role_rank(section) is not None for section in level):
            level.sort(key=role_rank)
        return level

    return ordered(sections)


# ---------------------------------------------------------------------------
# Index / link normalization / output writers (moved from nodes.py CombineTutorial)
# ---------------------------------------------------------------------------


def build_index_sections(lines, sections, chapter_files, level=3, summaries=None, descriptions=None):
    """Recursively build index.md sections with module tables.

    Description column: *descriptions* (module_name → one-line description from the grouping reply)
    first; otherwise, for the generic DeterministicFileMapper description ("Internal API reference
    for ..."), ``summary_description`` of *summaries* (module_name → chapter summary).
    """
    summaries = summaries or {}
    descriptions = descriptions or {}
    heading = "#" * level
    for section in sections:
        lines.append(f"{heading} {md_heading_text(section['name'])}")
        lines.append("")
        if section.get("modules"):
            lines.append(f"| {get('UI_TH_CHAPTER')} | {get('UI_TH_DESCRIPTION')} |")
            lines.append("|---------|-------------|")
            for mod_name in section["modules"]:
                match = next((cf for cf in chapter_files if cf["module_name"] == mod_name), None)
                if match:
                    desc = match["description"]
                    if desc.startswith("Internal API reference"):
                        desc = summaries.get(mod_name) or desc
                    cell = descriptions.get(mod_name) or summary_description(desc)
                    lines.append(f"| [{md_link_text(mod_name)}]({match['filename']}) | {cell} |")
            lines.append("")
        for child in section.get("children", []):
            build_index_sections(lines, [child], chapter_files, level + 1, summaries, descriptions)


def normalize_chapter_links(chapter_files):
    """Deterministic post-processing: fix all cross-chapter markdown link targets.

    Builds a lookup from known chapter filenames, then rewrites every
    ``[text](target.md)`` link so the target is a correct relative path
    from the current chapter's directory to the target chapter.
    """
    # Build lookup: every full path first (e.g. "CoreService/AccountingService.cs.md"), then a bare-basename
    # alias only for basenames that occur once and are not themselves a full path, so an alias can never
    # shadow or remove a real file (the result no longer depends on chapter order).
    filenames = [cf["filename"] for cf in chapter_files]
    filename_lookup = {fname: fname for fname in filenames}
    basename_counts = Counter(fname.rsplit("/", 1)[-1] for fname in filenames)
    for fname in filenames:
        basename = fname.rsplit("/", 1)[-1]
        if basename_counts[basename] == 1 and basename not in filename_lookup:
            filename_lookup[basename] = fname

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
                # Cached pages are normalized again on later runs, where a page-relative target that is also
                # another chapter's root-relative path would be read as that chapter: pin it with "./".
                if _dir and filename_lookup.get(correct_rel, canonical) != canonical:
                    correct_rel = f"./{correct_rel}"
                if correct_rel != target:
                    fixed_count += 1
                return f"[{text}]({correct_rel}{anchor})"
            return match.group(0)  # Unknown target — leave as-is

        cf["content"] = link_pattern.sub(fix_link, cf["content"])

    if fixed_count:
        emit_raw("DEBUG", f"LINK NORMALIZATION | fixed {fixed_count} cross-chapter links", dest="LOG")


def add_used_by_lines(chapter_files: list, module_facts: dict) -> None:
    """End each api-reference chapter (its See Also section) with a "Used by" line built from the verified
    importers in facts.json — deterministic, so an importer's edit never regenerates the page.

    The line from an earlier run (cached pages are re-read from disk) is replaced: only a prose line outside code
    blocks that starts with ``**`` and ends with ``USED_BY_MARKER`` counts, never a code or table line quoting the
    marker. Link targets are written page-relative (``./``-pinned like ``normalize_chapter_links``) and in ``<…>``
    when they hold spaces or parentheses (``app/(marketing)/page.tsx``). A page ending in a code block left open
    (a truncated reply) gets the block closed first, so the line is not swallowed by it."""
    doc_paths = {cf["original_path"]: cf["filename"] for cf in chapter_files if cf.get("original_path")}
    filenames = set(doc_paths.values())
    label = get("UI_USED_BY_LINE")
    for cf in chapter_files:
        facts = module_facts.get(cf.get("original_path") or "")
        if not facts:
            continue
        parsed = parse_page(cf["content"])
        generated = {number for number, text in parsed["prose"] if text.lstrip().startswith("**") and text.rstrip().endswith(USED_BY_MARKER)}
        content = "\n".join(text for number, text in enumerate(cf["content"].split("\n"), start=1) if number not in generated).rstrip()
        if parsed["unclosed"]:  # closed by the same fence at the same indentation (the only closer the site reads)
            opener = re.match(r"\s*(?:`{3,}|~{3,})", cf["content"].split("\n")[parsed["unclosed"][-1] - 1]).group(0)
            content += "\n" + opener
        users = [user for user in sorted(facts.get("used_by") or []) if user in doc_paths and user != cf.get("original_path")]
        if users:
            links = ", ".join(f"[{md_link_text(user)}]({_page_link(cf['filename'], doc_paths[user], filenames)})" for user in users)
            content += f"\n\n**{label}:** {links} {USED_BY_MARKER}"
        cf["content"] = content + "\n\n"


_REPAIRED_KINDS = ("lists_as_text", "tables_as_text", "lists_flattened")
_ITEM_START_RE = re.compile(r"^( *)([*+-]|\d{1,9}[.)])( +|$)")  # a list item line (tabs expanded): indent, marker, spaces
_FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_REPAIR_RENDERS = 40  # renders one page's repairs may take (each candidate is rendered)


def _indent_of(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _flattened_run(lines: list[str], index: int) -> int:
    """Index after the nested run starting at *index*: its items and everything indented under them."""
    indent, end = _indent_of(lines[index]), index + 1
    for position in range(index, len(lines)):
        if lines[position].strip():
            if _indent_of(lines[position]) < indent:
                break
            end = position + 1
    return end


def _repair(lines: list[str], kind: str, finding: dict) -> list[str]:
    """*lines* with one finding fixed: a blank line (``>`` in a quote) before a list or table left as text; a
    flattened nested list re-indented level by level, each level 4 spaces past the one above, an item's
    paragraphs 4 spaces past its marker and a fenced block moved as one piece (its code unchanged). A run with a
    tab in its indentation is left alone (moving it would change how its tabs line up)."""
    index = finding["line"] - 1
    if kind in ("lists_as_text", "tables_as_text"):
        if index == 0 or not lines[index - 1].strip():
            return lines
        quote = re.match(r"^(?: {0,3}> ?)+", lines[index])
        return [*lines[:index], quote.group(0).rstrip() if quote else "", *lines[index:]]
    indent = _indent_of(lines[index])
    parent = next((line for line in reversed(lines[:index]) if line.strip() and _indent_of(line) < indent), None)
    if parent is None or _indent_of(parent) + 4 <= indent:
        return lines
    end = _flattened_run(lines, index)
    if any("\t" in line[: len(line) - len(line.lstrip())] for line in lines[index:end]):
        return lines
    repaired = list(lines)
    levels = []  # (old indent, new indent, old text column) of the run's open items
    fence = None  # (closing-fence pattern, shift) while inside a fenced block
    for position in range(index, end):
        line = lines[position]
        if fence:
            if line.strip():
                repaired[position] = " " * fence[1] + line
            if fence[0].match(line):
                fence = None
            continue
        if not line.strip():
            continue
        old = _indent_of(line)
        item = _ITEM_START_RE.match(line.expandtabs(4))
        if item:
            while levels and old <= levels[-1][0]:
                levels.pop()
            new = levels[-1][1] + 4 if levels else _indent_of(parent) + 4
            spaces = len(item.group(3))
            levels.append((old, new, item.end(2) + (spaces if 1 <= spaces <= 4 else 1)))
            shift = new - old
        else:
            while levels and old < levels[-1][2]:  # not in that item's text any more
                levels.pop()
            shift = levels[-1][1] + 4 - levels[-1][2] if levels else 0
            opener = _FENCE_LINE_RE.match(line)
            if opener:
                fence = (re.compile(rf"^\s*{re.escape(opener.group(1)[0])}{{{len(opener.group(1))},}}\s*$"), max(shift, 0))
        if shift > 0:
            repaired[position] = " " * shift + line
    return repaired


def _visible(text: str) -> str:
    """The page's characters, whitespace and lone ``>`` lines left out: all a repair may change is those."""
    return re.sub(r"\s+", "", "\n".join(line for line in text.split("\n") if line.strip() != ">"))


def _code_blocks(text: str) -> list[str]:
    return [textwrap.dedent(block["text"]) for block in parse_page(text)["blocks"]]


def repair_markup(markdown: str, render) -> tuple[str, Counter]:
    """*markdown* with the lists and tables the site would show as text given the blank line they need, and
    flattened nested lists re-indented (``markup_problems`` finds them) — ``(markdown, fixed per kind)``. The
    templates ask for that layout; this catches what the writer still gets wrong.

    Guarded by the renderer: a repair is kept only when the page's visible text and every code block are
    unchanged, the CommonMark reading of every list item, paragraph, table and code block is the same
    (``markup_verdicts``) and every mark that rendered exactly still does while at least one more now does — so a
    repair never moves text into or out of a list item, turns an item into code or nests it deeper. All repairs
    are tried at once first, then one by one; rounds repeat for nested levels, within ``_REPAIR_RENDERS`` renders.
    What cannot be repaired this way stays for the chapter check to report."""
    renders = 0

    def verdicts(text: str) -> tuple[list, int]:
        nonlocal renders
        renders += 1
        return markup_verdicts(text, parse_page(text), render)

    def improved(candidate: str, before: tuple[list, int]) -> tuple[list, int] | None:
        """The candidate's verdicts when it is an acceptable repair of *current*, else None."""
        if candidate == current or _visible(candidate) != _visible(current) or _code_blocks(candidate) != _code_blocks(current):
            return None
        after = verdicts(candidate)
        (marks_before, code_before), (marks_after, code_after) = before, after
        if [(kind, reading) for kind, reading, _ok in marks_after] != [(kind, reading) for kind, reading, _ok in marks_before]:
            return None  # the writer's meaning would change
        wrong_before = {number for number, (_kind, _reading, ok) in enumerate(marks_before) if ok is False}
        wrong_after = {number for number, (_kind, _reading, ok) in enumerate(marks_after) if ok is False}
        vanished = any(ok is None and marks_before[number][2] is not None for number, (_kind, _reading, ok) in enumerate(marks_after))
        # text without a mark (a table row, a deeper line) turning into indented code shows only as an extra block
        return after if wrong_after < wrong_before and not vanished and code_after <= code_before else None

    current = markdown
    for _round in range(5):  # re-indenting a nested list can show the level below it flattened
        if renders >= _REPAIR_RENDERS:
            break
        found = markup_problems(current, parse_page(current), render)
        pending = [(kind, finding) for kind in _REPAIRED_KINDS for finding in found[kind]]
        if not pending:
            break
        before = verdicts(current)
        renders += 1  # markup_problems above
        # one repair per run: a flattened finding inside another's run is re-indented with it
        runs, kept = [], []
        lines = current.split("\n")
        for kind, finding in sorted(pending, key=lambda item: item[1]["line"]):
            index = finding["line"] - 1
            if kind == "lists_flattened":
                if any(start <= index < end for start, end in runs):
                    continue
                runs.append((index, _flattened_run(lines, index)))
            kept.append((kind, finding))
        kept.reverse()  # bottom-up, so the line numbers above stay valid while lines are inserted
        batch = lines
        for kind, finding in kept:
            batch = _repair(batch, kind, finding)
        after = improved("\n".join(batch), before)
        if after is not None:
            current = "\n".join(batch)
            continue
        progress = False
        for kind, finding in kept:
            if renders >= _REPAIR_RENDERS:
                break
            candidate = "\n".join(_repair(current.split("\n"), kind, finding))
            after = improved(candidate, before)
            if after is not None:
                current, before, progress = candidate, after, True
        if not progress:
            break
    if current == markdown:
        return markdown, Counter()
    start = markup_problems(markdown, parse_page(markdown), render)
    end = markup_problems(current, parse_page(current), render)
    return current, +Counter({kind: len(start[kind]) - len(end[kind]) for kind in _REPAIRED_KINDS})


_SEE_ALSO_ITEM_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)(?P<open>\*\*|__)?\[(?P<text>[^\]\n]+)\]\((?P<target><[^>\n]+>|[^)\s]+)\)(?P<close>\*\*|__)?"
    r"(?P<sep>\s*(?::|\s[-\u2013\u2014]|\u2014|\u2013)\s*|\s+)?(?P<rest>.*)$"  # separator: a colon, a hyphen, an en or em dash
)


def _see_also_lines(content: str, chapters: set, page: str) -> list[int]:
    """Line indices of the See Also list items: the last ``##`` section that links a chapter (the heading is
    translated, so it is found by position, as the chapter check finds it), outside code blocks."""
    parsed = parse_page(content)
    starts = [number for number, level, _text in parsed["headings"] if level == 2]
    if not starts:
        return []
    prose = dict(parsed["prose"])
    for start, end in reversed(list(zip(starts, [*starts[1:], len(content.split("\n")) + 1], strict=True))):
        items = [number - 1 for number in range(start + 1, end) if number in prose and _SEE_ALSO_ITEM_RE.match(prose[number])]
        targets = [_SEE_ALSO_ITEM_RE.match(prose[index + 1]).group("target").strip("<>") for index in items]
        if any(_resolve_page(page, target) in chapters for target in targets):
            return items
    return []


def _resolve_page(page: str, target: str) -> str:
    path = target.split("#", 1)[0]
    return posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else page


def normalize_see_also(chapter_files: list) -> int:
    """Give every See Also entry the same form, ``- [path/to/file.ext](target) — description``: the link neither
    bold nor code-formatted, its text the linked chapter's source path (as in the "Used by" line; kept, stripped
    of formatting, for a link to no chapter or a chapter without one), an em dash before the description. The
    template asks for that form; this evens out what the writer varies (bold links, code-formatted paths, colons).
    Returns the number of entries changed."""
    path_of = {cf["filename"]: cf.get("original_path") or "" for cf in chapter_files}
    changed = 0
    for cf in chapter_files:
        lines = cf["content"].split("\n")
        for index in _see_also_lines(cf["content"], set(path_of), cf["filename"]):
            match = _SEE_ALSO_ITEM_RE.match(lines[index])
            if bool(match.group("open")) != bool(match.group("close")):
                continue  # bold spanning more than the link: left as written
            target, rest = match.group("target"), match.group("rest").strip()
            source = path_of.get(_resolve_page(cf["filename"], target.strip("<>")))
            text = md_link_text(source) if source else re.sub(r"`+|\*\*|__", "", match.group("text")).strip()
            separator = " — " if match.group("sep") and match.group("sep").strip() else " "
            line = f"{match.group('prefix')}[{text}]({target})" + (f"{separator}{rest}" if rest else "")
            if line != lines[index]:
                lines[index] = line
                changed += 1
        cf["content"] = "\n".join(lines)
    return changed


def _page_link(page: str, target: str, filenames: set) -> str:
    """Link target from chapter *page* to chapter *target*, page-relative; ``./``-pinned when the relative path
    is also another chapter's root-relative path; in ``<…>`` when it holds spaces or parentheses."""
    directory = posixpath.dirname(page)
    relative = posixpath.relpath(target, directory) if directory else target
    if directory and relative in filenames and relative != target:
        relative = f"./{relative}"
    return f"<{relative}>" if re.search(r"[\s()]", relative) else relative


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

    # Chapter summaries (aligned with chapter_files, header line dropped) for the grouping prompt and index descriptions
    chapter_summaries = prep_res.get("chapter_summaries", [])
    summaries = [
        strip_summary_header(chapter_summaries[i]) if i < len(chapter_summaries) and chapter_summaries[i] else "" for i in range(len(chapter_files))
    ]
    summary_by_module = {cf["module_name"]: summary for cf, summary in zip(chapter_files, summaries, strict=True) if summary}

    # --- LLM-Assisted Nav Grouping (api-reference only, 6+ modules) ---
    # The same reply also carries one-line module descriptions and module dependencies (index page)
    sections, grouped = None, False
    descriptions, dependencies, has_facts, inferred_sources, verified = {}, {}, False, [], {}
    emit_raw("DEBUG", f"NAV GROUPING CHECK | mode={mode} | module_count={len(chapter_files)} | threshold=6", dest="LOG")
    if mode == "api-reference":
        # Source-verified dependencies (ExtractFacts) are shown to the grouping model and, per module, replace the
        # ones it infers; a module whose extraction failed keeps the reply's edges. With a flat nav (no grouping,
        # or it failed) they still draw the index diagrams
        module_facts = prep_res.get("module_facts") or {}
        with_facts = modules_with_facts(module_facts, chapter_files)
        has_facts = bool(with_facts)
        verified = verified_dependencies(module_facts, chapter_files)
    if mode == "api-reference" and len(chapter_files) > 5:
        try:
            # Listed in directory-tree order: chapter_files is in generation order (deepest directory first),
            # which would suggest a bottom-up reading order
            listed = sorted(zip(chapter_files, summaries, strict=True), key=lambda pair: tree_order_key(pair[0]))
            lines = []
            for cf, summary in listed:
                name = cf["module_name"]
                uses = f" (uses: {', '.join(verified.get(name) or ['none'])})" if name in with_facts else ""
                lines.append(f"- {name}{uses}: {summary or cf['description']}")
            module_list = "\n".join(lines)

            # Load grouping prompt template
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "common", "group_modules.md")
            with open(prompt_path, encoding="utf-8-sig") as f:
                group_template = f.read()

            language = prep_res.get("language", "english")
            language_note = f"Section names and module descriptions MUST be in {language}." if language.lower() != "english" else ""

            group_prompt = group_template.format(
                project_name=project_name,
                module_count=len(chapter_files),
                module_list=module_list,
                directory_tree=prep_res.get("directory_tree", "N/A"),
                language_note=language_note,
            )

            emit("LLM_CALL_GROUPING", count=len(chapter_files))

            log_token_estimation("NavGrouping", group_prompt, prep_res.get("max_tokens", 100000))
            parsed, sections = request_grouping(group_prompt, prep_res, chapter_files)
            descriptions, replied = grouping_extras(parsed, chapter_files)
            if has_facts:
                dependencies = {source: targets for source, targets in replied.items() if source not in with_facts} | verified
                inferred_sources = sorted(source for source in dependencies if source not in with_facts)
            else:
                dependencies = replied
            emit_raw(
                "DEBUG",
                f"NAV GROUPING EXTRAS | verified={has_facts} | descriptions={len(descriptions)}/{len(chapter_files)} "
                f"| modules_with_dependencies={len(dependencies)} | edges={sum(len(t) for t in dependencies.values())}",
                dest="LOG",
            )

            # Reading order (nav, index tables and diagrams all follow it), then "Other" last
            reply_order = [section["name"] for section in sections]
            sections = order_sections(sections, chapter_files)
            emit_raw(
                "DEBUG",
                f"NAV ORDER | reply={reply_order} | roles={[section.get('role') for section in sections]} "
                f"| reading={[section['name'] for section in sections]}",
                dest="LOG",
            )
            # Validate: ensure all modules are covered
            grouped_modules = collect_all_modules(sections)
            ungrouped = [cf["module_name"] for cf in sorted(chapter_files, key=tree_order_key) if cf["module_name"] not in grouped_modules]
            if ungrouped:
                sections += order_sections([{"name": get("UI_OTHER"), "modules": ungrouped}], chapter_files)

            nav_lines = build_grouped_nav(sections, chapter_files, indent=4)
            nav_lines.insert(0, "    - api/index.md")
            nav_label = mode_labels.get(mode, "Documentation")
            nav_snippet = f"nav:\n  - {nav_label}:\n" + "\n".join(nav_lines)
            grouped = True
            emit("DONE_GROUPING", count=len(sections))

        except Exception as e:
            emit("GROUP_ERROR_FALLBACK", error=e)
            emit_raw("ERROR", f"LLM grouping failed: {e}\n{traceback.format_exc()}", dest="LOG")
    if not grouped:
        nav_snippet = prep_res["nav_snippet"]  # the directory nav
        if mode == "api-reference":
            # The index groups modules by directory, like the nav, and keeps its section map and module dependency
            # graph, drawn from the verified dependencies (without a grouping reply: no one-line descriptions)
            sections = directory_sections(chapter_files)
            descriptions, dependencies, inferred_sources = {}, dict(verified), []

    emit_raw(
        "DEBUG",
        f"NAV SNIPPET FINAL | grouped={grouped} | index_sections={len(sections or [])} | nav_snippet_lines={nav_snippet.count(chr(10)) + 1}",
        dest="LOG",
    )
    emit_raw("DEBUG", f"NAV SNIPPET CONTENT:\n{nav_snippet}", dest="LOG")
    if grouped:
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
        ]
        # Architecture overview (section map) above the tables, full module dependency graph below them
        section_map, map_has_arrows, map_has_hubs = build_section_map(sections, dependencies)
        if section_map:
            index_lines += [f"## {get('UI_ARCH_OVERVIEW')}", "", "```mermaid", section_map, "```", ""]
            if map_has_arrows:  # no caption when there is nothing to explain (e.g. the reply had no dependencies)
                note = get("UI_SECTION_MAP_NOTE") + (" " + get("UI_SECTION_MAP_HUBS") if map_has_hubs else "")
                index_lines += [f"*{note}*", ""]
        index_lines += [f"## {chapter_index_label}", ""]
        build_index_sections(index_lines, sections, chapter_files, summaries=summary_by_module, descriptions=descriptions)
        module_graph, hub_threshold = build_module_graph(sections, dependencies, chapter_files)
        if module_graph:
            note = get("UI_MODULE_GRAPH_NOTE")
            if hub_threshold:
                note += " " + get("UI_MODULE_GRAPH_HUBS", count=hub_threshold)
            if has_facts:  # facts.json sits next to api/index.md
                provenance = get("UI_DEPS_PARTIAL", modules=", ".join(inferred_sources)) if inferred_sources else get("UI_DEPS_VERIFIED")
                note += f" {provenance} ([facts.json](facts.json))"
            index_lines += [f"## {get('UI_MODULE_DEPENDENCIES')}", "", "```mermaid", module_graph, "```", "", f"*{note}*", ""]
            if hub_threshold:  # who uses each hub: the graph shows only their count
                index_lines += [f"### {get('UI_SHARED_MODULES')}", "", f"*{get('UI_SHARED_MODULES_NOTE', count=hub_threshold)}*", ""]
                for hub, fan_in in build_hub_fan_ins(sections, dependencies, chapter_files, hub_threshold):
                    index_lines += [f"#### {md_heading_text(hub)}", "", "```mermaid", fan_in, "```", ""]
        index_content = "\n".join(index_lines)
    else:
        # Build a rich flat index with module listing table
        chapter_index_label = get("UI_CHAPTER_INDEX")
        chapters_label = get("UI_CHAPTERS")
        th_chapter = get("UI_TH_CHAPTER")
        th_description = get("UI_TH_DESCRIPTION")
        index_lines = [
            f"# {project_name} — {mode_label}",
            "",
            f"{mode_label} — **{project_name}** — **{len(chapter_files)}** {chapters_label}.",
            "",
        ]
        # tutorial/advanced/sdk: project summary, source line and relationship diagram (as in the standalone index.md)
        if prep_res.get("overview"):
            index_lines += [prep_res["overview"].rstrip(), ""]
        index_lines += [
            f"## {chapter_index_label}",
            "",
            f"| {th_chapter} | {th_description} |",
            "|---------|-------------|",
        ]
        # Rows in the flat nav's order: root files first, then directories alphabetically (a stable sort, so
        # tutorial/advanced/sdk, which have no original_path, keep chapter_order)
        rows = sorted(zip(chapter_files, summaries, strict=True), key=lambda pair: os.path.dirname(pair[0].get("original_path") or ""))
        for cf, summary in rows:
            # original_path already is "dir/name" (module_name may carry a dir prefix for duplicate basenames)
            display = cf.get("original_path") or cf["module_name"]
            index_lines.append(f"| [{md_link_text(display)}]({cf['filename']}) | {summary_description(summary or cf['description'])} |")
        index_lines.append("")
        index_content = "\n".join(index_lines)
    api_index_filepath = os.path.join(api_docs_path, "index.md")
    with open(api_index_filepath, "w", encoding="utf-8") as f:
        f.write(index_content)
    emit("FILE_WROTE", path=api_index_filepath)

    # --- Write nav_snippet.yml (next to mkdocs.yml: MkDocs publishes every non-Markdown file inside docs/) ---
    nav_filepath = os.path.join(output_path, "nav_snippet.yml")
    with open(nav_filepath, "w", encoding="utf-8") as f:
        f.write(nav_snippet)
    emit("FILE_WROTE", path=nav_filepath)
    legacy_nav_filepath = os.path.join(output_path, "docs", "nav_snippet.yml")  # written there before; drop it from the site
    if os.path.exists(legacy_nav_filepath):
        os.remove(legacy_nav_filepath)

    # --- Deterministic "Used by" line (verified importers), then normalize cross-chapter links ---
    add_used_by_lines(chapter_files, prep_res.get("module_facts") or {})
    normalize_chapter_links(chapter_files)
    normalize_see_also(chapter_files)

    # --- Lists and tables the site would show as text, flattened nested lists: repaired, render-verified ---
    render = site_renderer()
    if render:
        repaired = Counter()
        for chapter_info in chapter_files:
            chapter_info["content"], fixed = repair_markup(chapter_info["content"], render)
            if fixed:
                emit("MARKUP_REPAIRED_PAGE", page=chapter_info["filename"], fixed=", ".join(f"{kind} {count}" for kind, count in fixed.items()))
            repaired += fixed
        if repaired:
            emit("MARKUP_REPAIRED", **{kind: repaired[kind] for kind in _REPAIRED_KINDS})

    # --- Write chapter files ---
    for chapter_info in chapter_files:
        chapter_filepath = os.path.join(api_docs_path, chapter_info["filename"])
        os.makedirs(os.path.dirname(chapter_filepath), exist_ok=True)
        with open(chapter_filepath, "w", encoding="utf-8") as f:
            f.write(chapter_info["content"])
        emit("FILE_WROTE", path=chapter_filepath)

    # --- Remove pages left over from earlier runs ---
    prune_stale_pages(api_docs_path, chapter_files)

    # --- Check the written chapters (no LLM; report next to mkdocs.yml, not published), rendered like the site ---
    run_chapter_check(output_path, api_docs_path, chapter_files, prep_res, render=render)


def prune_stale_pages(api_docs_path, chapter_files):
    """Delete .md pages under docs/api/ that belong to no current chapter, plus directories left empty.

    docs/api/ is generator-owned. Pages of removed, renamed or filtered-out modules (or from an
    earlier run in another mode) would otherwise stay published and searchable, because MkDocs
    builds every .md in docs_dir even when the nav no longer lists it.

    Pages are matched by file identity (device + inode), not path text: on a case-insensitive
    filesystem a case-only rename rewrites the existing entry, which keeps its old spelling.
    """

    def identity(path):
        st = os.stat(path)
        return st.st_dev, st.st_ino

    keep = set()
    for filename in ["index.md", *(cf["filename"] for cf in chapter_files)]:
        path = os.path.join(api_docs_path, filename)
        if os.path.exists(path):
            keep.add(identity(path))
    for root, _dirs, files in os.walk(api_docs_path, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            if name.endswith(".md") and identity(path) not in keep:
                os.remove(path)
                emit("MKDOCS_PRUNED_STALE", path=path)
        if os.path.normcase(root) != os.path.normcase(api_docs_path) and not os.listdir(root):
            os.rmdir(root)


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

    # Write chapter files (api-reference: with the deterministic "Used by" line; See Also entries in one form)
    add_used_by_lines(chapter_files, prep_res.get("module_facts") or {})
    normalize_see_also(chapter_files)
    for chapter_info in chapter_files:
        chapter_filepath = os.path.join(output_path, chapter_info["filename"])
        with open(chapter_filepath, "w", encoding="utf-8") as f:
            f.write(chapter_info["content"])
        emit("FILE_WROTE", path=chapter_filepath)
    run_chapter_check(output_path, output_path, chapter_files, prep_res, standalone=True)  # no LLM; report only

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
