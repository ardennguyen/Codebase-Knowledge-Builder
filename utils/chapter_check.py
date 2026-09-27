"""Deterministic checks of written chapters — no LLM, report only (pages are never changed).

Every page: links that point at no page, Mermaid blocks that will not render and code fences left open. MkDocs
output: Markdown the site's renderer reads differently than written (lists and tables shown as text, nested lists
flattened, lists cut apart, code blocks not rendered), found by rendering the page with the site's own pipeline.
Pages whose file has verified facts (api-reference, ExtractFacts): verified symbols the page never names,
signatures that differ from the source, type names in headings that exist nowhere in the code, and See Also links
compared with the verified dependencies. Language-agnostic like utils/facts.py: word tokens and the file's own
text only.
"""

import json
import os
import posixpath
import re
from html.parser import HTMLParser
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
# Markdown the site renders differently than written (markup_problems)
_LIST_ITEM_RE = re.compile(r"^( *)([*+-]|(\d{1,9})[.)])( +|$)")  # a CommonMark list item start (tabs expanded)
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,}|=+[ \t]*)$")  # also a setext underline
_TABLE_DELIMITER_RE = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$")
_MARK = "{}"  # private-use characters: no Markdown meaning, kept as they are by the renderer
_MARK_RE = re.compile("(\\d+)")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCK_TAGS = {"p", "li", "ul", "ol", "blockquote", "div", "pre", "table", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt"}
_VISIBLE_MARKER_RE = re.compile(r"^\s*(?:[*+-]|\d{1,9}[.)])(?:\s|$)")  # a rendered line still led by a list marker
_QUOTE_RE = re.compile(r"^(?: {0,3}> ?)+")
_CELL_PIPE_RE = re.compile(r"(?<!\\)\|")
_HARD_BREAK_RE = re.compile(r"(?:[ \t]+|\\)?$")  # a line's trailing spaces or backslash (a hard line break)
# CommonMark HTML blocks (raw on GitHub): those that run to an end marker, block-level tags, a tag alone on its line
_HTML_RAW_BLOCKS = tuple(
    (re.compile(start, re.IGNORECASE), re.compile(end, re.IGNORECASE))
    for start, end in (
        (r"^ {0,3}<(?:pre|script|style|textarea)(?:\s|>|$)", r"</(?:pre|script|style|textarea)>"),
        (r"^ {0,3}<!--", r"-->"),
        (r"^ {0,3}<\?", r"\?>"),
        (r"^ {0,3}<!\[CDATA\[", r"\]\]>"),
        (r"^ {0,3}<![A-Za-z]", r">"),
    )
)
_HTML_BLOCK_RE = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|"
    r"fieldset|figcaption|figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    r"noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:\s|/?>|$)",
    re.IGNORECASE,
)
_HTML_TAG_LINE_RE = re.compile(
    r"""^ {0,3}(?:<[A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z_:][\w.:-]*(?:\s*=\s*(?:[^\s"'=<>`]+|'[^']*'|"[^"]*"))?)*\s*/?>"""
    r"""|</[A-Za-z][A-Za-z0-9-]*\s*>)\s*$"""
)
_MARKUP_KEYS = {
    "lists_as_text": "CHAPTER_CHECK_MARKUP_LISTS_AS_TEXT",
    "lists_flattened": "CHAPTER_CHECK_MARKUP_LISTS_FLATTENED",
    "lists_merged": "CHAPTER_CHECK_MARKUP_LISTS_MERGED",
    "lists_split": "CHAPTER_CHECK_MARKUP_LISTS_SPLIT",
    "tables_as_text": "CHAPTER_CHECK_MARKUP_TABLES_AS_TEXT",
    "code_blocks_not_rendered": "CHAPTER_CHECK_MARKUP_CODE_BLOCKS",
}
_MARKUP_KINDS = tuple(_MARKUP_KEYS)
_LIST_RUNS = ("lists_as_text", "lists_flattened", "lists_merged")  # reported once per list, with its item count
# The deterministic "Used by" line (utils/mkdocs.py), built at run time so this source never holds it literally
# (a page quoting this line must not look like the generated line)
USED_BY_MARKER = "<!-- " + "used-by:auto" + " -->"
REPORT_FILENAME = "chapter_check.json"


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def parse_page(markdown: str) -> dict:
    """``{"prose": [(line, text)], "blocks": [{"lang", "start", "end", "text"}], "headings": [(line, level, text)],
    "unclosed": [line]}``.

    The page as written, read like CommonMark (GitHub): fenced code blocks (``` or ~~~ — a backtick fence's info
    string holds no backtick — closed by a line of just a fence of the same character at least as long, at most
    three spaces deeper than the opener) are separated from prose; line numbers are 1-based (``start`` / ``end``:
    the opening and closing fence lines). A fence still open at the end of the page is no block: its lines are
    prose again, and the opener is listed in ``unclosed``. Where the site's stricter renderer reads the page
    differently is found by rendering it (``markup_problems``)."""
    lines = markdown.split("\n")
    prose, blocks, headings, unclosed = [], [], [], []
    number = 0
    while number < len(lines):
        line = lines[number]
        opener = _FENCE_RE.match(line)
        if opener and opener.group(2)[0] == "`" and "`" in line[opener.end(2) :]:  # ```mermaid``` in prose: inline code
            opener = None
        if opener:
            indent, fence = len(opener.group(1)), opener.group(2)
            for end in range(number + 1, len(lines)):
                closer = _FENCE_RE.match(lines[end])
                if (
                    closer
                    and closer.group(2)[0] == fence[0]
                    and len(closer.group(2)) >= len(fence)
                    and not lines[end][closer.end(2) :].strip()
                    and len(closer.group(1)) <= indent + 3
                ):
                    blocks.append({"lang": opener.group(3).lower(), "start": number + 1, "end": end + 1, "text": "\n".join(lines[number + 1 : end])})
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


def _cells(row: str) -> int:
    row = row.strip().removeprefix("|")
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return len(re.split(r"(?<!\\)\|", row))


def _cell_cut(line: str, start: int) -> int:
    """Where a mark goes in a table header row: before the pipe that ends its first cell (an escaped ``\\|`` is
    cell text), so the row keeps its cells; -1 when the row has no such pipe (the mark goes at the end)."""
    body = line[start:]
    offset = start + len(body) - len(body.lstrip()) + (1 if body.lstrip().startswith("|") else 0)
    match = _CELL_PIPE_RE.search(line, offset)
    return match.start() if match else -1


def _html_block_end(lines: list[str], index: int, content: str, previous: str) -> int | None:
    """Index of the first line after the CommonMark HTML block starting at *index* — raw HTML on GitHub too,
    nothing to compare — or None when the line starts none: ``<pre>`` / ``<script>`` / ``<style>`` /
    ``<textarea>``, comments and declarations run to their end marker, block-level tags (``<div>``,
    ``<details>`` …) and a tag alone on its line (not right after a text line) to the next blank line."""
    for start, end in _HTML_RAW_BLOCKS:
        if start.match(content):
            if end.search(content):
                return index + 1
            return next((line + 1 for line in range(index + 1, len(lines)) if end.search(lines[line])), len(lines))
    if _HTML_BLOCK_RE.match(content) or (previous != "text" and _HTML_TAG_LINE_RE.match(content)):
        return next((line for line in range(index + 1, len(lines)) if not lines[line].strip()), len(lines))
    return None


def _intended_marks(lines: list[str], blocks: list[dict]) -> list[tuple[int, str, dict]]:
    """``(line index, kind, expectation)`` for the lines whose rendering is compared, read as CommonMark (GitHub)
    reads them, blockquote contents included: list items (``item``: nesting ``depth``, ``numbered``; ``start``
    when a numbered list begins past 1, ``continues`` for a numbered item of a list already open), paragraphs
    that continue a list item after a blank line or a code block (``content``), table header rows (``table``:
    GitHub splits one off a paragraph; ``item`` when inside a list item, ``cut`` where its mark goes), the first
    code line of every fenced block (``code``: its ``opener`` line, ``item``) and the first line after a block
    (``after``: prose a block not closed as written would swallow). HTML blocks are raw on GitHub: skipped."""
    fences = {block["start"] - 1: block for block in blocks}
    marks, stack = [], []  # stack: (content column, numbered) of the open list items, outermost first
    previous, after, depth = "blank", None, 0
    index = 0
    while index < len(lines):
        quote = _QUOTE_RE.match(lines[index])
        prefix = quote.group(0) if quote else ""
        if prefix.count(">") != depth:  # a quote starts or ends: its content is read on its own
            depth, stack, previous = prefix.count(">"), [], "blank"
        expanded = lines[index][len(prefix) :].expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))
        if index in fences:
            block = fences[index]
            while stack and indent < stack[-1][0]:
                stack.pop()
            first = next((line for line in range(index + 1, block["end"] - 1) if lines[line].strip()), None)
            if first is not None:
                marks.append((first, "code", {"opener": index + 1, "item": bool(stack), "depth": len(stack) - 1}))
            index, previous, after = block["end"], "other", index + 1
            continue
        if not expanded.strip():
            index, previous = index + 1, "blank"
            continue
        base = stack[-1][0] if stack and indent >= stack[-1][0] else 0  # the open item's content column
        following = _QUOTE_RE.sub("", lines[index + 1]).expandtabs(4) if index + 1 < len(lines) else ""
        head, delimiter = expanded[base:], following[base:] if not following[:base].strip() else following
        table = (
            len(head) - len(head.lstrip()) <= 3
            and "|" in head
            and "|" in delimiter
            and _TABLE_DELIMITER_RE.match(delimiter)
            and _cells(head) == _cells(delimiter)
        )
        rule = indent <= 3 and _THEMATIC_BREAK_RE.match(expanded)  # a mark would make it text: the next line gets it
        html = None if table or rule else _html_block_end(lines, index, expanded, previous)
        if after and not (table or rule or html):  # a table's own mark shows where its header landed
            marks.append((index, "after", {"opener": after}))
        if not rule:
            after = None
        if html is not None:
            while stack and indent < stack[-1][0]:
                stack.pop()
            index, previous = html, "other"
            continue
        if rule or (indent <= 3 and _HEADING_RE.match(expanded.lstrip())):
            stack.clear()
            index, previous = index + 1, "other"
            continue
        item = _LIST_ITEM_RE.match(expanded)
        # an item nests at most 3 columns past its parent's content (more is indented code); outside a list, only
        # a bullet or a list starting at 1, not empty, interrupts a paragraph
        if (
            item
            and indent < (stack[-1][0] if stack else 0) + 4
            and not (previous == "text" and not stack and (item.group(3) not in (None, "1") or not expanded[item.end() :].strip()))
        ):
            numbered, popped = item.group(3) is not None, None
            while stack and indent < stack[-1][0]:
                popped = stack.pop()
            spaces = len(item.group(4))
            stack.append((item.end(2) + (spaces if 1 <= spaces <= 4 else 1), numbered))
            if expanded[item.end() :].strip():  # an empty item gets no mark: a lone "-" marked would stop being a setext underline
                expect = {"depth": len(stack) - 1, "numbered": numbered}
                if numbered:
                    if popped is None or not popped[1]:  # no numbered sibling before it: a new list
                        if item.group(3) != "1":
                            expect["start"] = int(item.group(3))
                    else:
                        expect["continues"] = True
                marks.append((index, "item", expect))
            index, previous = index + 1, "item"
            continue
        if table:
            if previous != "text":
                while stack and indent < stack[-1][0]:
                    stack.pop()
            marks.append((index, "table", {"item": bool(stack), "depth": len(stack) - 1, "cut": _cell_cut(lines[index], len(prefix))}))
            index, previous = index + 2, "table"
            continue
        if previous == "table":  # table rows run until a blank line or another block
            index += 1
            continue
        if previous in ("blank", "other"):
            while stack and indent < stack[-1][0]:
                stack.pop()
            if stack and indent < stack[-1][0] + 4:  # 4 columns past the item's text: indented code there too
                marks.append((index, "content", {"depth": len(stack) - 1}))
        index, previous = index + 1, "text"
    return marks


class _MarkContexts(HTMLParser):
    """Where each mark landed in the rendered page: ``found[mark] = {"li", "depth", "number", "list", "th", "code",
    "marker"}`` — inside a list item (its list's nesting depth, the item's position in that list, the list's tag),
    a table header cell, a code block (``code``: the block's number; ``<pre>`` or a Mermaid ``div``, its text read
    whole since highlighting splits it into spans), and whether the rendered line still starts with a list marker
    (a list shown as text, even inside an item)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.items, self.found = [], [], {}
        self.code = None  # (stack depth, context, text parts) of the code block being read
        self.blocks = 0  # code blocks seen
        self.text = ""  # rendered text of the current block so far

    def _context(self, code: int | None = None, marker: bool = False) -> dict:
        tags = [tag for tag, _classes in self.stack]
        lists = [tag for tag in tags if tag in ("ul", "ol")]
        return {
            "li": "li" in tags,
            "depth": len(lists) - 1,
            "number": self.items[-1] if self.items else 0,
            "list": lists[-1] if lists else None,
            "th": "th" in tags,
            "code": code,
            "marker": marker,
        }

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.text += "\n"
        if tag in _VOID_TAGS:
            return
        if tag in _BLOCK_TAGS:
            self.text = ""
        classes = (dict(attrs).get("class") or "").split()
        self.stack.append((tag, classes))
        if tag in ("ul", "ol"):
            self.items.append(0)
        elif tag == "li" and self.items:
            self.items[-1] += 1
        if self.code is None and (tag == "pre" or "mermaid-raw" in classes):
            self.blocks += 1
            self.code = (len(self.stack), self._context(self.blocks), [])

    def handle_endtag(self, tag):
        depth = next((depth for depth in range(len(self.stack) - 1, -1, -1) if self.stack[depth][0] == tag), None)
        if depth is None:
            return
        if tag in _BLOCK_TAGS:
            self.text = ""
        if self.code and depth < self.code[0]:
            for match in _MARK_RE.finditer("".join(self.code[2])):
                self.found[int(match.group(1))] = self.code[1]
            self.code = None
        for closed, _classes in self.stack[depth:]:
            if closed in ("ul", "ol") and self.items:
                self.items.pop()
        del self.stack[depth:]

    def handle_data(self, data):
        if self.code:
            self.code[2].append(data)
            return
        for match in _MARK_RE.finditer(data):
            line = (self.text + data[: match.start()]).rsplit("\n", 1)[-1]
            self.found[int(match.group(1))] = self._context(marker=bool(_VISIBLE_MARKER_RE.match(line)))
        self.text += data


def _rendered_marks(markdown: str, parsed: dict, render) -> tuple[list[str], list, dict, int]:
    """``(lines, marks, found, code blocks)``: the page's intended marks (``_intended_marks``), where each landed
    when the marked page is rendered (``_MarkContexts.found``, by mark number) and how many code blocks it has."""
    # the renderer reads a lone \r as a line break (a mark after it would move to a line of its own); a page's own
    # private-use characters must not read as marks — neither changes the line numbers
    lines = markdown.replace("\r\n", "\n").replace("", "").replace("", "").split("\n")
    marks = _intended_marks(lines, parsed["blocks"])
    tagged = list(lines)
    for number, (index, kind, expect) in enumerate(marks):
        mark, line = _MARK.format(number), tagged[index]
        cut = expect["cut"] if kind == "table" else _HARD_BREAK_RE.search(line).start()  # before a hard break's spaces / "\"
        tagged[index] = line[:cut] + mark + line[cut:] if cut >= 0 else line + mark
    contexts = _MarkContexts()
    contexts.feed(render("\n".join(tagged)))
    contexts.close()
    return lines, marks, contexts.found, contexts.blocks


def _mark_ok(kind: str, expect: dict, where: dict) -> bool:
    """Whether one mark rendered exactly as CommonMark reads it: a list item in a list item of the right depth
    and list type, its marker consumed; an item's paragraph, table or code inside that item's depth; a table
    header in a header cell; code in a code block; the line after a block not swallowed by code."""
    in_item = where["li"] and where["depth"] == expect.get("depth")
    if kind == "item":
        return in_item and not where["marker"] and not where["code"] and where["list"] == ("ol" if expect["numbered"] else "ul")
    if kind == "content":
        return in_item and not where["code"]
    if kind == "table":
        return where["th"] and (not expect["item"] or in_item)
    if kind == "code":
        return bool(where["code"]) and (not expect["item"] or in_item)
    return not where["code"]


def markup_verdicts(markdown: str, parsed: dict, render) -> tuple[list[tuple[str, tuple, bool | None]], int]:
    """``([(kind, expectation, ok)], code blocks)``: per intended mark, in page order, the CommonMark reading (line
    positions left out, so a repair that only moves lines compares equal) and whether the site renders it exactly
    so (``None``: the mark vanished into raw HTML or a comment); and the number of code blocks the site renders
    (text without a mark turning into indented code shows only there). Stricter than ``markup_problems``, which
    reports only what a reader notices; ``utils/mkdocs.repair_markup`` keeps a repair only when the reading is
    unchanged, no mark renders worse and no code block is added."""
    _lines, marks, found, code_blocks = _rendered_marks(markdown, parsed, render)
    verdicts = []
    for number, (_index, kind, expect) in enumerate(marks):
        reading = tuple(sorted((key, value) for key, value in expect.items() if key not in ("opener", "cut")))
        where = found.get(number)
        verdicts.append((kind, reading, None if where is None else _mark_ok(kind, expect, where)))
    return verdicts, code_blocks


def markup_problems(markdown: str, parsed: dict, render) -> dict:
    """Markdown the site renders differently than written: ``{kind: [finding]}`` for ``_MARKUP_KINDS``.

    The page is read as CommonMark (GitHub) reads it — what the writer means — and rendered with the site's own
    Markdown pipeline (*render*: markdown → HTML, ``utils/mkdocs.site_renderer``), stricter than GitHub: a list or
    table right after a text line, a label or a code block stays text; nested items and an item's paragraphs,
    code and tables need 4 spaces; a numbered list right after a bulleted one (or the reverse) joins it; every
    list is numbered from 1; the opening fence may hold only the language (and ``title`` / ``linenums`` /
    ``hl_lines``), and closes only at the same fence and indentation. Each list item, table header row, first
    code line, list-item paragraph and line after a code block gets an invisible mark, and where the mark lands in
    the rendered HTML says how it rendered — exact, since it is the renderer itself. Findings: ``lists_as_text``
    / ``lists_flattened`` (``{"line", "items"}``, one per list), ``lists_merged``, ``lists_split`` (an item's
    paragraph, code or table shown after the list, or a numbered list not starting at its number),
    ``tables_as_text``, ``code_blocks_not_rendered`` (``{"line", "opener"}``: also a block whose missing closer
    swallows the text after it — reported once, and not again for the next block, whose opening fence the
    renderer took as that closer)."""
    lines, marks, found, _code_blocks = _rendered_marks(markdown, parsed, render)
    owners = {}  # rendered code block -> [(mark, opener)] of the fenced blocks whose first code line it shows
    for number, (_index, kind, expect) in enumerate(marks):
        if kind == "code" and found.get(number) and found[number]["code"]:
            owners.setdefault(found[number]["code"], []).append((number, expect["opener"]))
    problems = {kind: [] for kind in _MARKUP_KINDS}
    blamed = set()  # fenced blocks already reported

    def blame(opener: int) -> None:
        if opener not in blamed:
            blamed.add(opener)
            problems["code_blocks_not_rendered"].append({"line": opener, "opener": lines[opener - 1].strip()[:80]})

    split_since_item, run, item_listed, last_block = False, None, True, None  # run: list items being folded
    for number, (index, kind, expect) in enumerate(marks):
        where = found.get(number)
        if where is None:  # the mark vanished (raw HTML, a comment): nothing to compare
            continue
        if kind != "code" and where["code"]:
            # swallowed by a code block: blame the fenced block that opened it (its first code line is there, before
            # this mark); none when it is an indented or raw <pre> block, or opened by a stray fence of a block
            # already reported
            opened = [opener for mark, opener in owners.get(where["code"], []) if mark < number]
            if opened:
                blame(opened[-1])
            run = None
            continue
        problem = None
        if kind == "after":
            continue
        if kind == "item":
            if not where["li"] or where["marker"]:
                problem = "lists_as_text"
            elif where["depth"] < expect["depth"]:
                problem = "lists_flattened"
            elif where["list"] != ("ol" if expect["numbered"] else "ul"):
                problem = "lists_merged"
            elif ("start" in expect or expect.get("continues")) and where["number"] == 1 and not split_since_item:
                problem = "lists_split"
            split_since_item, item_listed = False, where["li"] and not where["marker"]
        elif kind == "content":  # outside the list, or in a shallower item than its own
            problem = "lists_split" if item_listed and (not where["li"] or where["depth"] < expect["depth"]) else None
        elif kind == "table":
            if not where["th"]:
                problem = "tables_as_text"
            elif expect["item"] and item_listed and (not where["li"] or where["depth"] < expect["depth"]):
                problem = "lists_split"
        else:
            knock_on, last_block = last_block in blamed, expect["opener"]
            if not where["code"]:
                if not knock_on:  # else its opening fence was taken as the closer of the block before, reported
                    blame(expect["opener"])
                run = None
                continue
            if expect["item"] and item_listed and (not where["li"] or where["depth"] < expect["depth"]):
                problem = "lists_split"
        if problem is None:
            run = None
            continue
        if problem == "lists_split" and kind != "item":
            split_since_item = True
        if problem in _LIST_RUNS and run and run[0] == problem:
            between = [line.strip() for line in lines[run[2] + 1 : index]]
            if all(between) or not any(between):  # the same list, tight or loose
                run[1]["items"] += 1
                run = (problem, run[1], index)
                continue
        finding = {"line": expect["opener"] if kind == "code" else index + 1}
        if problem in _LIST_RUNS:
            finding["items"] = 1
            run = (problem, finding, index)
        else:
            run = None
        problems[problem].append(finding)
    return problems


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
    page: str,
    markdown: str,
    exists,
    module: str = "",
    facts: dict | None = None,
    source: str = "",
    known_words=None,
    module_by_page=None,
    render=None,
) -> dict:
    """All checks for one written chapter → report dict (empty lists when nothing is wrong). Facts of a file
    whose extraction failed (``claims`` None) are not used. With *render* (the site's Markdown renderer, MkDocs
    output) the ``markup_problems`` too."""
    parsed = parse_page(markdown)
    report = {
        "page": page,
        "module": module,
        "broken_links": broken_links(page, parsed, exists),
        "diagram_problems": diagram_problems(parsed),
        "unclosed_fences": [{"line": line} for line in parsed["unclosed"]],
    }
    if render:
        report |= markup_problems(markdown, parsed, render)
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
_COUNTED = ("broken_links", "diagram_problems", "unclosed_fences", *_MARKUP_KINDS, *_FACT_KINDS)


def _line_list(findings: list[dict], limit: int = 10) -> str:
    lines = [str(finding["line"]) for finding in findings]
    return ", ".join(lines[:limit]) + (" …" if len(lines) > limit else "")


def run_chapter_check(output_path: str, site_dir: str, chapter_files: list, prep_res: dict, standalone: bool = False, render=None) -> dict:
    """Check every written chapter, write ``chapter_check.json`` next to the output (not published), emit a
    summary plus a warning per broken link, per diagram that will not render and per page and kind of Markdown
    the site renders differently than written, and return the report.

    *site_dir*: folder the chapter filenames are relative to (``docs/api`` for MkDocs, the output folder
    for standalone). ``prep_res`` may carry ``module_facts`` (ExtractFacts), ``sources`` ({path: content}
    of the documented files) and ``known_words`` (identifier tokens of every crawled file). Standalone output is
    never pruned, so there a link to an ``.md`` file counts only when it is a current page (not a stale
    ``NN_`` page of an earlier run). *render*: the site's Markdown renderer (MkDocs output, ``site_renderer``);
    standalone pages are read by GitHub-style renderers, so they get no ``markup_problems``."""
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
            cf["filename"], cf["content"], exists, module, module_facts.get(module), sources.get(module, ""), known_words, module_by_page, render
        )
        reports.append(report)
        for problem in report["broken_links"]:
            emit("CHAPTER_CHECK_BROKEN_LINK", page=cf["filename"], line=problem["line"], target=problem["target"])
        grouped = {}
        for problem in report["diagram_problems"]:
            grouped.setdefault((problem["diagram"], problem["problem"]), []).append(str(problem["line"]))
        for (diagram, problem), lines in grouped.items():  # one warning per diagram and kind, its lines listed
            emit(_DIAGRAM_KEYS[problem], page=cf["filename"], line=", ".join(lines), diagram=diagram)
        for kind in _MARKUP_KINDS:  # one warning per page and kind, its lines listed
            if report.get(kind):
                emit(_MARKUP_KEYS[kind], page=cf["filename"], count=len(report[kind]), lines=_line_list(report[kind]))
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
    if render:
        emit("CHAPTER_CHECK_MARKUP", **{kind: totals[kind] for kind in _MARKUP_KINDS})
    if any("missing_symbols" in report for report in reports):  # pages with verified facts
        emit("CHAPTER_CHECK_FACTS", **{kind: totals[kind] for kind in _FACT_KINDS})
    return document


def source_context(files_data: list) -> tuple[dict, set]:
    """``(sources, known_words)`` for ``run_chapter_check``: every crawled file's text by forward-slash path,
    and the identifier tokens of all of them (a type name the page uses must occur somewhere in the code)."""
    sources = {path.replace(os.sep, "/"): content for path, content in files_data}
    known_words = {word for content in sources.values() for word in re.findall(r"\w+", content)}
    return sources, known_words
