"""Deterministic checks of written chapters — no LLM, report only (pages are never changed).

Every page: links that point at no page, Mermaid blocks that will not render and code fences left open. Pages
whose file has verified facts (api-reference, ExtractFacts): verified symbols the page never names, signatures
that differ from the source, type names in headings that exist nowhere in the code, and See Also links compared
with the verified dependencies. Language-agnostic like utils/facts.py: word tokens and the file's own text only.
"""

import json
import os
import posixpath
import re
from urllib.parse import unquote

from utils.facts import _DECLARATION_MODIFIERS, _DECLARATION_WORDS, _TOP_LEVEL_WORDS, _names_in
from utils.output import emit

_WORD_RE = re.compile(r"[^\W\d][\w$]*")
_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([\w+-]*)")
# [text](target "title"): target in <...>, or with one level of balanced parentheses; images too
_LINK_RE = re.compile(
    r"(?<!\\)!?\[(?:[^\[\]\\]|\\.|!?\[[^\]]*\](?:\([^)]*\))?)*\]\(\s*(<[^>\n]+>|(?:[^()\s]|\([^()\s]*\))+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
_REFERENCE_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>\n]+>|\S+)")  # [ref]: target
_IMAGE_RE = re.compile(r"(?<!\\)!\[[^\]]*\]\(\s*(<[^>\n]+>|[^()\s]+)")  # an image, also one nested in a link's text
_HTML_HREF_RE = re.compile(r"<a\s[^>]*?href\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# A bold label, then an inline code span: **Signature**: `def f(x):` (any language; a full-width colon too, inside or after the bold)
_LABELLED_CODE_RE = re.compile(r"\*\*[^*\n]{1,40}?[:\uff1a]?\*\*\s*[:\uff1a]?\s*(`+)(.+?)\1")
_BLOCK_LABEL_RE = re.compile(r"^\*\*[^*\n]{1,40}?[:\uff1a]?\*\*\s*[:\uff1a]?\s*$")
_DECORATOR_LINE_RE = re.compile(r"^\s*(?:@|#\[|\[[A-Z])")  # @property, #[inline], [Obsolete]
_COMMENT_LINE_RE = re.compile(r"^\s*(?:#|//|/\*|\*|--|;|%)")  # a code block's leading comment lines
# Words that start a declaration head (def, func, fn, class, public, static, async, export, constructor, …)
_DECLARATION_START = _DECLARATION_WORDS | _DECLARATION_MODIFIERS | _TOP_LEVEL_WORDS | {"pub", "void", "extern"}
_NOT_DECLARATION = {
    "await",
    "return",
    "new",
    "yield",
    "throw",
    "raise",
    "print",
    "echo",
    "if",
    "elif",
    "else",
    "for",
    "while",
    "switch",
    "match",
    "with",
    "try",
    "catch",
    "except",
}
_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]*)?=>"
)
_NAME_BEFORE_PAREN_RE = re.compile(r"([^\W\d][\w$]*[?!]?)\s*(?:<[^()]*>|\[[^()]*\])?\s*\(")
_PARAM_TOKEN_RE = re.compile(r"[\w$]+|\.\.\.|[*&\[\]?]")  # words plus the punctuation that changes a type
# A type-like name: starts uppercase, has another capital and a lowercase letter (FactClaim, LLMConfigTuple)
_TYPE_NAME_RE = re.compile(r"^_*[A-Z](?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*?[A-Z][A-Za-z0-9]*?[A-Z]|[A-Za-z0-9]*[a-z][A-Za-z0-9]*[A-Z])[A-Za-z0-9]+$")
_MERMAID_TYPES = (
    "flowchart", "flowchart-elk", "graph", "sequenceDiagram", "classDiagram", "classDiagram-v2", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "mindmap", "timeline", "gitGraph", "quadrantChart",
    "requirementDiagram", "C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment", "sankey-beta",
    "xychart-beta", "block-beta", "packet-beta", "architecture-beta", "kanban", "radar-beta", "treemap-beta", "zenuml",
)  # fmt: skip
_DIAGRAM_KEYS = {
    "type": "CHAPTER_CHECK_DIAGRAM_TYPE",
    "arrow": "CHAPTER_CHECK_DIAGRAM_ARROW",
    "quotes": "CHAPTER_CHECK_DIAGRAM_QUOTES",
    "brackets": "CHAPTER_CHECK_DIAGRAM_BRACKETS",
    "label": "CHAPTER_CHECK_DIAGRAM_LABEL",
}
# The deterministic "Used by" line (utils/mkdocs.py), built at run time so this source never holds it literally
# (a page quoting this line must not look like the generated line)
USED_BY_MARKER = "<!-- " + "used-by:auto" + " -->"
REPORT_FILENAME = "chapter_check.json"


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def parse_page(markdown: str) -> dict:
    """``{"prose": [(line, text)], "blocks": [{"lang", "start", "text"}], "headings": [(line, level, text)],
    "unclosed": [line]}``.

    Fenced code blocks (``` or ~~~, closed by a fence of the same character at least as long, at most three
    spaces deeper than the opener) are separated from prose; line numbers are 1-based. A fence still open at the
    end of the page is no block (as the MkDocs renderer reads it): its lines are prose again, and the opener is
    listed in ``unclosed``."""
    lines = markdown.split("\n")
    prose, blocks, headings, unclosed = [], [], [], []
    number = 0
    while number < len(lines):
        line = lines[number]
        opener = _FENCE_RE.match(line)
        if opener:
            indent, fence = len(opener.group(1)), opener.group(2)
            for end in range(number + 1, len(lines)):
                closer = _FENCE_RE.match(lines[end])
                if (
                    closer
                    and closer.group(2)[0] == fence[0]
                    and len(closer.group(2)) >= len(fence)
                    and not closer.group(3)
                    and len(closer.group(1)) <= indent + 3
                ):
                    blocks.append({"lang": opener.group(3).lower(), "start": number + 1, "text": "\n".join(lines[number + 1 : end])})
                    number = end + 1
                    break
            else:
                unclosed.append(number + 1)
                prose.append((number + 1, line))
                number += 1
            continue
        prose.append((number + 1, line))
        heading = _HEADING_RE.match(line)
        if heading:
            headings.append((number + 1, len(heading.group(1)), heading.group(2)))
        number += 1
    return {"prose": prose, "blocks": blocks, "headings": headings, "unclosed": unclosed}


def _links(prose: list) -> list[tuple[int, str]]:
    """``(line, target)`` of every Markdown link, image and reference definition outside code (inline code spans
    and HTML comments left out; escaped ``\\[`` is no link)."""
    found = []
    for number, line in prose:
        text = _HTML_COMMENT_RE.sub("", _CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line))
        for pattern in (_LINK_RE, _IMAGE_RE, _HTML_HREF_RE):
            found.extend((number, match.group(1)) for match in pattern.finditer(text))
        reference = _REFERENCE_RE.match(text)
        if reference:
            found.append((number, reference.group(1)))
    targets = [(number, target[1:-1] if target.startswith("<") else target) for number, target in found]
    return list(dict.fromkeys(targets))


def resolve_link(page: str, target: str) -> str | None:
    """A page-relative link target → path relative to the site folder of the pages; None for external
    links (``https:``, ``mailto:`` …), same-page anchors and absolute paths. ``%20`` and other escapes are
    decoded, as the renderer does."""
    if re.match(r"^[a-zA-Z][\w+.-]*:", target) or target.startswith(("#", "/")):
        return None
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    return posixpath.normpath(posixpath.join(posixpath.dirname(page), path)) if path else None


def broken_links(page: str, parsed: dict, exists) -> list[dict]:
    """Links whose target is no page or file of the output (*exists*: site-relative path → bool)."""
    problems = []
    for number, target in _links(parsed["prose"]):
        resolved = resolve_link(page, target)
        if resolved is not None and not exists(resolved):
            problems.append({"line": number, "target": target})
    return problems


def mermaid_problems(source: str) -> list[dict]:
    """Syntax problems that stop a Mermaid block from rendering: ``{"line", "problem"}`` with problem
    ``type`` (the first line names no diagram type), and for flowcharts ``arrow`` (``>>``, a code operator,
    is no Mermaid arrow), ``quotes`` (odd number of ``"``), ``brackets`` (unbalanced outside labels) or
    ``label`` (a bracket inside an unquoted ``[...]`` label, which Mermaid reads as a shape).
    Conservative: only what makes Mermaid's parser fail, so a report is always worth reading."""
    lines = source.split("\n")
    body = [(number, line) for number, line in enumerate(lines, start=1) if line.strip() and not line.strip().startswith("%%")]
    if body and body[0][1].strip() == "---":  # frontmatter (title / config) before the diagram type
        closing = next((i for i, (_n, line) in enumerate(body[1:], start=1) if line.strip() == "---"), None)
        body = body[closing + 1 :] if closing is not None else []
    if not body:
        return []
    first = body[0][1].strip().split()[0].rstrip(":")
    if first not in _MERMAID_TYPES:
        return [{"line": body[0][0], "problem": "type"}]
    if not first.startswith(("flowchart", "graph")):
        return []
    markdown_strings = '"`' in source  # "`multi-line markdown labels`" span lines: quote and bracket counts do not apply
    problems = []
    for number, line in body[1:]:
        if line.count('"') % 2 and not markdown_strings:
            problems.append({"line": number, "problem": "quotes"})
            continue
        code = re.sub(r'"[^"]*"', '""', line)
        code = re.sub(r"\|[^|]*\|", "||", code)  # edge labels: A -->|label| B
        code = re.sub(r"\w>[^\]]*\]", "x", code)  # the asymmetric shape: id>label]
        unlabelled = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", "", code)  # `>>` inside a label is text
        if re.search(r"(?<![-=.])>>", unlabelled):
            problems.append({"line": number, "problem": "arrow"})
        elif re.search(r"\w\[(?![(\[/\\])[^\]\"]*[(\[{]", code):  # A[run(x)] — not the shapes A[(db)], A[[sub]], A[/p/]
            problems.append({"line": number, "problem": "label"})
        elif not markdown_strings and any(code.count(o) != code.count(c) for o, c in ("[]", "()", "{}")):
            problems.append({"line": number, "problem": "brackets"})
    return problems


def diagram_problems(parsed: dict) -> list[dict]:
    """``mermaid_problems`` of every ```mermaid block, with the block's number and page line."""
    diagrams = [block for block in parsed["blocks"] if block["lang"] == "mermaid"]
    return [
        {"diagram": number, "line": block["start"] + problem["line"], "problem": problem["problem"]}
        for number, block in enumerate(diagrams, start=1)
        for problem in mermaid_problems(block["text"])
    ]


def _page_text(parsed: dict) -> str:
    """Prose and code of a page, Mermaid left out (a diagram label does not document a symbol)."""
    code = [block["text"] for block in parsed["blocks"] if block["lang"] != "mermaid"]
    return "\n".join([line for _n, line in parsed["prose"]] + code)


def missing_symbols(parsed: dict, symbols: list[dict]) -> list[dict]:
    """Verified symbols whose name the page never writes (prose or code), matched like facts.py matches
    names: word tokens, and verbatim for names with punctuation (``valid?``, ``operator==``)."""
    text = _page_text(parsed)
    words = set(re.findall(r"\w+", text)) | {word.lstrip("$") for word in re.findall(r"\$\w+", text)}
    words |= set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", text))  # an identifier glued to CJK prose: 调用run_flow函数
    missing = []
    for symbol in symbols:
        name = str(symbol.get("name", "")).split(".")[-1].lstrip("$")
        if name and not (name in words or _names_in(text, name)):
            missing.append({k: symbol.get(k) for k in ("name", "kind", "parent", "line")})
    return missing


def _is_subsequence(wanted: list[str], have: list[str]) -> bool:
    position = 0
    for word in have:
        if position < len(wanted) and word == wanted[position]:
            position += 1
    return position == len(wanted)


def _strip_decorators(text: str) -> str:
    """A declaration without its leading decorator / attribute / comment lines (``@property``, ``#[inline]``)."""
    lines = text.split("\n")
    while lines and (not lines[0].strip() or _DECORATOR_LINE_RE.match(lines[0]) or _COMMENT_LINE_RE.match(lines[0])):
        lines = lines[1:]
    return "\n".join(lines)


def _head(text: str) -> str:
    """A declaration up to the line where the parenthesis after its name closes (a quoted signature may run on
    into the body); the whole text when it never closes (a signature cut short)."""
    text = _strip_decorators(text)
    name = _declared_name(text)
    start = name[1] if name else text.find("(")
    if start < 0:
        return text.split("\n", 1)[0]
    depth = 0
    for position in range(start, len(text)):
        char = text[position]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
            if depth <= 0:
                end = text.find("\n", position)
                return text if end < 0 else text[:end]
    return text


def _declared_name(text: str) -> tuple[str, int] | None:
    """``(name, position of its "(")`` of a declaration head: an arrow function's variable (``const add = (a) =>``),
    else the first name right before a ``(`` (generics between allowed: ``first<T>(``, ``Map[T any](``), a Go
    receiver ``func (c *Cache) Get(`` skipped."""
    arrow = _ARROW_RE.match(text)
    if arrow:
        return arrow.group(1), text.find("(", arrow.end(1))
    receiver = re.match(r"^\s*func\s*\([^)]*\)", text)
    found = _NAME_BEFORE_PAREN_RE.search(text, receiver.end() if receiver else 0)
    return (found.group(1), found.end() - 1) if found else None


def _declaration_shaped(text: str) -> bool:
    """A declaration head rather than a reference or a call: led by a declaration word or modifier (``def``,
    ``func``, ``public``, ``static`` …), or with a type before the name (``int size()``), or a body
    opener after it (``run() {``, ``get(key): number;``) — never a receiver-qualified call (``flow.run(shared)``,
    ``c->get()``) or a statement (``await x(…)``, ``return f(…)``, ``y = f(…)``)."""
    text = _strip_decorators(text).strip()
    first = (_words(text) or [""])[0]
    name = _declared_name(text)
    if not name or first in _NOT_DECLARATION:
        return False
    if first in _DECLARATION_START:
        return True
    if first in ("constructor", "init") and re.search(r"\(\s*[\w$]+\s*:", text):
        return True  # constructor(size: string), init(name: Int) — typed, unlike a call init(language="x")
    before = text[: name[1]].rstrip()
    before = before[: len(before) - len(name[0])] if before.endswith(name[0]) else before
    if before.endswith((".", "->")) or "=" in before:
        return False
    if before.endswith("::") and not _words(before.rstrip(":").rsplit(None, 1)[0] if " " in before.strip() else ""):
        return False  # A::b(…) with no type before it is a call; `void A::b(` is a definition
    head = _head(text).rstrip()
    return len(_words(before)) >= 1 or head.endswith(("{", ":", ";"))


def _signatures(parsed: dict) -> list[tuple[int, str]]:
    """``(line, text)`` of the declarations the page labels as such: an inline code span right after a bold label
    (``**Signature**: `def f(x):` ``, whatever the label's language or colon), or the declaration a code block opens
    with (decorators and comments skipped, several lines joined) when the block follows a bold label line."""
    found = []
    prose = dict(parsed["prose"])
    for number, line in parsed["prose"]:
        found.extend((number, match.group(2).strip()) for match in _LABELLED_CODE_RE.finditer(line) if _declaration_shaped(match.group(2)))
    for block in parsed["blocks"]:
        label = prose.get(block["start"] - 1, "").strip()
        if block["lang"] == "mermaid" or not (_BLOCK_LABEL_RE.match(label) and re.search(r"[:\uff1a]", label)):
            continue
        head = _head(block["text"])
        if _declaration_shaped(head):
            found.append((block["start"] + 1, head.strip()))
    return found


def _params(head: str) -> tuple[list[list[str]], bool] | None:
    """The parameter list after the declared name: one token list per parameter (words plus ``* & [ ] ... ?``),
    and whether the list closes (a cut-short signature does not). None without a parameter list."""
    name = _declared_name(head)
    if not name:
        return None
    params, current, depth = [], "", 0
    text = head[name[1] + 1 :]
    for position, char in enumerate(text):
        pair = text[max(0, position - 1) : position + 1]
        if char in "([{" or (char == "<" and pair != "<="):
            depth += 1
        elif char in ")]}" or (char == ">" and pair not in ("->", "=>", ">=")):
            if depth == 0 and char == ")":
                params.append(current)
                return [_PARAM_TOKEN_RE.findall(p) for p in params if p.strip()], True
            depth -= 1
        elif char == "," and depth == 0:
            params.append(current)
            current = ""
            continue
        current += char
    params.append(current)
    return [_PARAM_TOKEN_RE.findall(p) for p in params if p.strip()], False


def _compare(page_head: str, source_head: str) -> str:
    """``same``, ``embellished`` (only tokens added: type annotations, return types) or ``mismatch`` (a parameter
    added, dropped, renamed or reordered, a default or a pointer / list / variadic marker changed)."""
    have, wanted = _PARAM_TOKEN_RE.findall(page_head), _PARAM_TOKEN_RE.findall(source_head)
    if have == wanted:
        return "same"
    page, source = _params(page_head), _params(source_head)
    if page is None or source is None:
        return "embellished" if _is_subsequence(wanted, have) else "mismatch"
    (page_params, _page_closed), (source_params, source_closed) = page, source
    if not source_closed:  # a cut-short verified signature: its complete parameters are a prefix
        source_params = source_params[:-1]
        if len(page_params) < len(source_params):
            return "mismatch"
        page_params = page_params[: len(source_params)]
    elif len(page_params) != len(source_params):
        return "mismatch"
    if not all(_is_subsequence(want, got) for want, got in zip(source_params, page_params, strict=True)):
        return "mismatch"
    # the parameters hold; a return type the source writes must still be there (only added tokens are harmless)
    return "embellished" if not source_closed or _is_subsequence(wanted, have) else "mismatch"


def signature_issues(parsed: dict, source: str, symbols: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(mismatches, embellished)`` for the page's labelled signatures.

    A signature found verbatim in the source (whitespace ignored) is fine. Otherwise it is compared with the
    verified signatures of the symbol it declares (decorators stripped, cut at the closing parenthesis): the
    same parameters with only tokens added (type annotations the source lacks) is ``embellished``; a parameter
    added, dropped, renamed or reordered is a ``mismatch``. Names with no verified symbol (nested helpers) are
    skipped."""
    flat_source = _collapse(source)
    by_name = {}
    for symbol in symbols:
        by_name.setdefault(str(symbol.get("name", "")).split(".")[-1], []).append(_head(str(symbol.get("signature", ""))))
    mismatches, embellished = [], []
    for number, text in _signatures(parsed):
        if _collapse(text).rstrip(":{; ") in flat_source:
            continue
        name = _declared_name(text)
        candidates = by_name.get(name[0]) if name else None
        if not candidates:
            continue
        verdicts = [_compare(_head(text), candidate) for candidate in candidates]
        if "same" in verdicts:
            continue
        if "embellished" in verdicts:
            embellished.append({"line": number, "signature": text})
        else:
            mismatches.append({"line": number, "signature": text, "source": _collapse(candidates[0])[:200]})
    return mismatches, embellished


def unknown_type_names(parsed: dict, known_words: set) -> list[dict]:
    """Type-like names written as code in headings (``### `FactClaim` ``, ``### Stream result (`StreamResult`)``)
    that occur in no crawled file: the writer named a dict or tuple shape as if it were a declared type. Names
    starting with an acronym count (``LLMConfigTuple``); brand names in heading prose do not."""
    if not known_words:
        return []
    found = []
    for number, _level, text in parsed["headings"]:
        spans = " ".join(match.group(2) for match in _CODE_SPAN_RE.finditer(text))
        names = sorted(set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", spans)))  # ASCII: a name glued to CJK text still counts
        found.extend({"line": number, "name": word} for word in names if _TYPE_NAME_RE.match(word) and word not in known_words)
    return found


def _see_also_section(parsed: dict, pages: set, page: str) -> list[tuple[int, str]]:
    """Prose lines of the See Also section, the deterministic Used-by line left out. See Also is last in the
    api-reference skeleton and its heading is translated, so it is found by position: the last ``##`` section
    that links a chapter (a trailing section the writer added after it links none), else the last one."""
    starts = [number for number, level, _text in parsed["headings"] if level == 2]
    if not starts:
        return []
    sections = [
        [(number, line) for number, line in parsed["prose"] if start < number < end and USED_BY_MARKER not in line]
        for start, end in zip(starts, [*starts[1:], float("inf")], strict=True)
    ]
    for section in reversed(sections):
        if any(resolve_link(page, target) in pages for _number, target in _links(section)):
            return section
    return sections[-1]


def see_also_issues(page: str, parsed: dict, module: str, module_by_page: dict, facts: dict) -> tuple[list, list]:
    """``(unrelated, missing)``: See Also links to modules with no verified import in either direction, and
    verified dependencies the section does not link."""
    depends = {edge["module"] for edge in facts.get("depends_on", [])} & set(module_by_page.values())  # only documented ones can be linked
    related = depends | set(facts.get("used_by", []))
    linked = {}
    pages = set(module_by_page)
    section = _see_also_section(parsed, pages, page)
    for number, target in _links(section):
        resolved = resolve_link(page, target)
        target_module = module_by_page.get(resolved) if resolved else None
        if target_module and target_module != module:
            linked.setdefault(target_module, number)
    unrelated = [{"line": number, "module": target} for target, number in sorted(linked.items(), key=lambda item: item[1]) if target not in related]
    missing = [{"module": target} for target in sorted(depends - set(linked))]
    return unrelated, missing


def check_chapter(
    page: str, markdown: str, exists, module: str = "", facts: dict | None = None, source: str = "", known_words=None, module_by_page=None
) -> dict:
    """All checks for one written chapter → report dict (empty lists when nothing is wrong). Facts of a file
    whose extraction failed (``claims`` None) are not used."""
    parsed = parse_page(markdown)
    report = {
        "page": page,
        "module": module,
        "broken_links": broken_links(page, parsed, exists),
        "diagram_problems": diagram_problems(parsed),
        "unclosed_fences": [{"line": line} for line in parsed["unclosed"]],
    }
    if facts and facts.get("claims") is not None:
        symbols = facts.get("symbols", [])
        mismatches, embellished = signature_issues(parsed, source, symbols)
        unrelated, missing = see_also_issues(page, parsed, module, module_by_page or {}, facts)
        report |= {
            "missing_symbols": missing_symbols(parsed, symbols),
            "signature_mismatches": mismatches,
            "signatures_embellished": embellished,
            "unknown_type_names": unknown_type_names(parsed, known_words or set()),
            "see_also_unrelated": unrelated,
            "see_also_missing_dependencies": missing,
        }
    return report


_FACT_KINDS = (
    "missing_symbols", "signature_mismatches", "signatures_embellished", "unknown_type_names", "see_also_unrelated",
    "see_also_missing_dependencies",
)  # fmt: skip
_COUNTED = ("broken_links", "diagram_problems", "unclosed_fences", *_FACT_KINDS)


def run_chapter_check(output_path: str, site_dir: str, chapter_files: list, prep_res: dict, standalone: bool = False) -> dict:
    """Check every written chapter, write ``chapter_check.json`` next to the output (not published), emit a
    summary plus a warning per broken link and per diagram that will not render, and return the report.

    *site_dir*: folder the chapter filenames are relative to (``docs/api`` for MkDocs, the output folder
    for standalone). ``prep_res`` may carry ``module_facts`` (ExtractFacts), ``sources`` ({path: content}
    of the documented files) and ``known_words`` (identifier tokens of every crawled file). Standalone output is
    never pruned, so there a link to an ``.md`` file counts only when it is a current page (not a stale
    ``NN_`` page of an earlier run)."""
    module_facts = prep_res.get("module_facts") or {}
    sources = prep_res.get("sources") or {}
    known_words = prep_res.get("known_words") or set()
    pages = {cf["filename"] for cf in chapter_files}
    module_by_page = {cf["filename"]: cf.get("original_path") for cf in chapter_files if cf.get("original_path")}
    generated = {"index.md", "full_content.md", "facts.json"}

    def exists(path):
        if path in pages or path in generated:
            return True
        if standalone and path.endswith(".md"):
            return False
        return os.path.exists(os.path.join(site_dir, *path.split("/")))

    reports = []
    for cf in chapter_files:
        module = cf.get("original_path") or ""
        report = check_chapter(
            cf["filename"], cf["content"], exists, module, module_facts.get(module), sources.get(module, ""), known_words, module_by_page
        )
        reports.append(report)
        for problem in report["broken_links"]:
            emit("CHAPTER_CHECK_BROKEN_LINK", page=cf["filename"], line=problem["line"], target=problem["target"])
        grouped = {}
        for problem in report["diagram_problems"]:
            grouped.setdefault((problem["diagram"], problem["problem"]), []).append(str(problem["line"]))
        for (diagram, problem), lines in grouped.items():  # one warning per diagram and kind, its lines listed
            emit(_DIAGRAM_KEYS[problem], page=cf["filename"], line=", ".join(lines), diagram=diagram)
        for kind in _FACT_KINDS:
            for item in report.get(kind, []):
                emit("CHAPTER_CHECK_DETAIL", page=cf["filename"], kind=kind, detail=json.dumps(item, ensure_ascii=False))
    totals = {kind: sum(len(report.get(kind, [])) for report in reports) for kind in _COUNTED}
    totals["diagrams_failing"] = sum(len({problem["diagram"] for problem in report["diagram_problems"]}) for report in reports)
    document = {"pages": len(reports), "totals": totals, "reports": reports}
    report_path = os.path.join(output_path, REPORT_FILENAME)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=1, ensure_ascii=False)
    emit(
        "CHAPTER_CHECK_DONE",
        pages=len(reports),
        path=report_path,
        broken_links=totals["broken_links"],
        diagram_problems=totals["diagrams_failing"],
        unclosed_fences=totals["unclosed_fences"],
    )
    if any("missing_symbols" in report for report in reports):  # pages with verified facts
        emit("CHAPTER_CHECK_FACTS", **{kind: totals[kind] for kind in _FACT_KINDS})
    return document


def source_context(files_data: list) -> tuple[dict, set]:
    """``(sources, known_words)`` for ``run_chapter_check``: every crawled file's text by forward-slash path,
    and the identifier tokens of all of them (a type name the page uses must occur somewhere in the code)."""
    sources = {path.replace(os.sep, "/"): content for path, content in files_data}
    known_words = {word for content in sources.values() for word in re.findall(r"\w+", content)}
    return sources, known_words
