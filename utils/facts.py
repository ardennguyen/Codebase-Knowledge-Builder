"""Verified code facts (api-reference): language-agnostic checks of LLM claims against the source.

ExtractFacts asks the LLM (prompts/common/extract_facts.md) for one file's symbols, dependencies,
config keys and errors, each with a line quoted from the source. Nothing here parses a programming
language. A claim is kept only when its quote is found in the file: whitespace-collapsed on one
line, joined across a few lines, or as its identifier tokens in order within a few lines. A
dependency is kept only when the quoted line names the target module, by its file stem as part of a
path, or by a name that only that module defines. Line numbers come from the match, never from
the LLM. Verification proves that a listed fact is in the source, not that the lists are complete.
"""

import hashlib
import json
import os
import posixpath
import re
import subprocess
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from itertools import accumulate

FACTS_SCHEMA = 1
FACTS_FILENAME = "facts.json"
CLAIM_KEYS = ("symbols", "dependencies", "config", "errors")

_WINDOW = 8  # lines a quote may span (joined imports, multi-line signatures); longer quotes get their own length
_MIN_TOKEN_QUOTE = 3  # identifier tokens needed before the in-order token fallback is trusted
_EXCERPT = 300  # longest source text stored per fact (a minified one-line file would repeat itself per fact)
_CALL_SPAN_LINES = 12  # lines a config/error quote's open bracket may run on (a multi-line `add_argument(` call)
_STRING_RE = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`")  # one-line string literals
# Error role, from the text before the name: a handler keyword after the last raise keyword → caught (`except X:`,
# `} catch (X e)`, `rescue X`, Dart `on X catch`); a raise keyword → raised; neither (a definition, a return) → mentioned
_HANDLER_RE = re.compile(r"(?<![\w.$@])@?(?:except\*?|catch|rescue|recover)(?![\w$])", re.IGNORECASE)
_RAISE_RE = re.compile(r"(?<![\w$])(?:(?<!\.)(?:raise|throw|throws|panic|Err|abort|error|fail|reject)|Errorf)(?![\w$])")  # fmt.Errorf, not log.error
_ROLE_RANK = {"raised": 0, "mentioned": 1, "caught": 2}  # of several places, the one that raises the error wins
_COMMENT_START_RE = re.compile(r"^\s*(?:#|//|/\*|\*|--)")  # a comment line (C preprocessor lines too)
# An access label or a bare keyword line inside a block: `public slots:`, `signals:`, `private`, `where`
_LABEL_RE = re.compile(r"\s*([A-Za-z_]\w*)[\w\s]*:\s*|\s*([a-z_]\w*)\s*")
# unexplained_names: names the file binds itself (declarations, assignments, keyword arguments) and names it uses
_NAME = r"[^\W\d][\w$]*"
_KEYWORD_BINDS_RE = re.compile(
    rf"(?<![\w$.])(?:for|let|var|val|const)[ \t]+[(\[{{]?[ \t]*((?:{_NAME}[ \t]*,[ \t]*)*{_NAME})(?=[ \t]*(?:[,)\]}}=:;]|in\b|of\b|$))", re.MULTILINE
)  # for a, b in …, const {a, b} = …, let [x, y] = …, val repo: Repository = … (the type is not bound)
_LINE_BINDS_RE = re.compile(rf"^[ \t]*((?:{_NAME}[ \t]*,[ \t]*)*{_NAME})[ \t]*:?=(?![=>])", re.MULTILINE)  # a, b := …; x = …
_KWARG_BINDS_RE = re.compile(rf"[(,][ \t]*({_NAME})[ \t]*=(?![=>])")  # f(name=…), def f(x=1) — not `x: Type = …`
_FIRST_NAME_RE = re.compile(r"(?<![\w$])(?:(?<=\.\.)|(?<!\.))([^\W\d][\w$]*)")  # a name not after one dot (`..MAX` counts)
_DOTTED_RE = re.compile(r"(?<![\w$.])[^\W\d][\w$]*(?:\.[^\W\d][\w$]*)+")  # Shop.Cart.add, os.environ.get
_SHELL_VAR_RE = re.compile(r"\$\{?([A-Za-z_]\w*)")  # $NAME, ${NAME}
_INTERPOLATION_RE = re.compile(r"\$\{([^}]*)\}|#\{([^}]*)\}|\\\(([^)]*)\)")  # ${expr}, #{expr}, \(expr)
_WORD_RE = re.compile(r"\w+")
_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")  # what editors, GitHub and models count; str.splitlines also splits at \f, \x85, U+2028
_DOTTED_RE = re.compile(r"\w+(?:(?:\.|::|\\)\w+)+")
# Characters that make a name part of a path or module reference: utils.output, ./client, "net/socket.h",
# crate::store, <vector>, App\Db
_QUALIFIERS = set("./\\:\"'<`")
_CLOSERS = set("\"'`>")
# First words of import-like lines across languages. A hint for the evidence rule and the recall scan,
# never enough on its own: the line must still name the target module.
_IMPORT_WORDS = {
    "import",
    "from",
    "require",
    "require_relative",
    "require_once",
    "include",
    "include_once",
    "using",
    "use",
    "mod",
    "export",
    "load",
    "source",
    "extern",
    "uses",
    "library",
    "open",
    "alias",
    "part",
}
_MODIFIERS = {"pub", "crate", "public", "private", "protected", "internal", "static"}
_CONTAINER_KINDS = {"class", "struct", "interface", "enum", "trait", "type", "module", "namespace", "impl", "object", "record", "protocol"}
_OWNER_EXCLUDED_KINDS = {"method"}  # called on objects of any type: proves nothing about which file a line uses
_NAMESPACE_WORDS = {"namespace", "package", "module", "defmodule", "library", "unit"}  # declaration lines
_INDEX_STEMS = ("mod", "index", "__init__", "init", "main", "lib")  # the file a directory import means, in this preference
_BARE_NAME_RE = re.compile(r"^[\w-]+$")  # a package name without any path part
_SEGMENT_RE = re.compile(r"^[\w$@~-]+$")  # path segments; drops grouped-import lists such as {Repo, StoreError}
_GO_BLOCK_LINE_RE = re.compile(r'^\s*(?:[\w.]+\s+)?"[^"]+"\s*$')  # a bare quoted path, e.g. inside import ( ... )


def split_lines(content: str) -> list[str]:
    """Lines as editors and GitHub number them (only CR, LF, CRLF break a line)."""
    lines = _LINE_BREAK_RE.split(content)
    return lines[:-1] if lines and lines[-1] == "" else lines


def _nfc(text) -> str:
    return unicodedata.normalize("NFC", str(text))


def _collapse(text: str) -> str:
    return " ".join(_nfc(text).split())


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", _nfc(text))


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(_nfc(text))


class SourceIndex:
    """One file's lines, pre-normalized for quote matching (NFC: models write precomposed letters)."""

    def __init__(self, content: str):
        self.lines = split_lines(_nfc(content))
        self.collapsed = [_collapse(line) for line in self.lines]
        # Collapsed lines joined by "\n" (never inside a collapsed line or quote, so no match spans two lines)
        self.collapsed_text = "\n".join(self.collapsed) + "\n"
        self.collapsed_offsets = list(accumulate((len(line) + 1 for line in self.collapsed), initial=0))
        squashed = [_squash(line) for line in self.lines]
        # All lines without whitespace, back to back, with each line's start offset: one str.find per quote
        self.squashed_text = "".join(squashed)
        self.offsets = list(accumulate((len(line) for line in squashed), initial=0))
        self.words = [_words(line) for line in self.lines]
        self.word_sets = [set(words) for words in self.words]
        self.word_lines = defaultdict(list)  # word → lines it occurs on, for the token fallback
        for number, words in enumerate(self.word_sets):
            for word in words:
                self.word_lines[word].append(number)
        self._chains = None  # block_chain(), built on first use

    def block_chain(self, line: int) -> tuple:
        """The blocks *line* sits in, innermost first: ``(indent, text, kind, named)`` per enclosing line
        (``_block_chains``)."""
        if self._chains is None:
            self._chains = _block_chains(self.lines)
        return self._chains[line]

    def text(self, first: int, last: int) -> str:
        return "\n".join(self.lines[first : last + 1])

    def locate(self, quote, start: int = 0, end: int | None = None) -> list[tuple[int, int, str]]:
        """``[(first_line, last_line, how)]`` (0-based) where *quote* occurs in lines ``start..end``.

        ``how`` is ``exact`` (on one line, whitespace collapsed), ``joined`` (across up to
        ``_WINDOW`` lines, or the quote's own line count, whitespace ignored) or ``tokens`` (its
        identifier tokens in order within that many lines, e.g. a model joining a Go import block line
        with its ``import`` keyword). Only the first kind that matches anywhere is returned.
        """
        end = len(self.lines) if end is None else min(end, len(self.lines))
        collapsed = _collapse(quote)
        if not collapsed or start >= end:
            return []
        exact = []
        pos = self.collapsed_text.find(collapsed, self.collapsed_offsets[start])
        while 0 <= pos < self.collapsed_offsets[end]:
            line = bisect_right(self.collapsed_offsets, pos) - 1
            exact.append((line, line, "exact"))
            pos = self.collapsed_text.find(collapsed, self.collapsed_offsets[line + 1])  # next line: one hit per line
        if exact:
            return exact
        window = max(_WINDOW, len(split_lines(str(quote))) + 1)
        squashed = _squash(quote)
        joined = []
        pos = self.squashed_text.find(squashed, self.offsets[start])
        while 0 <= pos < self.offsets[end]:
            first = bisect_right(self.offsets, pos) - 1
            last = bisect_right(self.offsets, pos + len(squashed) - 1) - 1
            if last - first < window and last < end:
                joined.append((first, last, "joined"))
            pos = self.squashed_text.find(squashed, pos + 1)
        if joined:
            return list(dict.fromkeys(joined))
        words = _words(quote)
        if len(words) < _MIN_TOKEN_QUOTE or any(word not in self.word_lines for word in words):
            return []
        # Only windows around the quote's rarest word can hold all of its words
        rarest = min((self.word_lines[word] for word in words), key=len)
        starts = sorted({i for line in rarest for i in range(max(start, line - window + 1), min(line + 1, end))})
        found = []
        for i in starts:
            if words[0] not in self.word_sets[i]:
                continue
            last = self._words_in_order(words, i, min(i + window, end))
            if last is not None:
                found.append((i, last, "tokens"))
        return found

    def _words_in_order(self, words: list[str], first: int, end: int) -> int | None:
        position = 0
        for line in range(first, end):
            for word in self.words[line]:
                if word == words[position]:
                    position += 1
                    if position == len(words):
                        return line
        return None

    def excerpt(self, first: int, last: int, quote) -> tuple[str, bool]:
        """The matched source text, at most ``_EXCERPT`` characters around the quote: ``(text, truncated)``. A
        quote longer than the window keeps its start (a long signature keeps its keyword and name)."""
        text = self.text(first, last).strip()
        if len(text) <= _EXCERPT:
            return text, False
        flat, wanted = _collapse(text), _collapse(quote)
        pos = max(flat.find(wanted), 0)
        start = max(0, min(pos - max(0, (_EXCERPT - len(wanted)) // 2), len(flat) - _EXCERPT))
        return flat[start : start + _EXCERPT], True


def _has_words(text: str, name: str) -> bool:
    """Whether the identifier tokens of *name* occur in *text* in order (``--max-size`` → max, size)."""
    wanted, have = _words(name), _words(text)
    if not wanted:
        return False
    position = 0
    for word in have:
        if word == wanted[position]:
            position += 1
            if position == len(wanted):
                return True
    return False


def _names_in(text: str, name: str) -> bool:
    """Whether *name* occurs in *text*: by its word tokens, and for names with punctuation (``operator==``,
    ``==``, ``[]``, ``<>``) also verbatim with whitespace ignored, so a wrong operator never passes."""
    if re.fullmatch(r"\w+", _nfc(name)):
        return _has_words(text, name)
    return _squash(name) in _squash(text) and (not _words(name) or _has_words(text, name))


def _as_text(value) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    return value if isinstance(value, str) else str(value) if isinstance(value, (int, float)) else ""


def _claim_list(claims: dict, key: str) -> list[dict]:
    items = claims.get(key) if isinstance(claims, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


# ---------------------------------------------------------------------------
# Per-file verification (no knowledge of other modules)
# ---------------------------------------------------------------------------


def verify_file_claims(claims: dict, content: str) -> dict:
    """Check one file's claims against its own source.

    Returns ``{"symbols", "dependencies", "config", "errors", "rejected", "claimed", "found"}``:
    kept claims carry the real source text (at most ``_EXCERPT`` characters, ``truncated`` when cut)
    and 1-based ``line``; errors also a ``role``, ``raised``, ``caught`` or ``mentioned`` (``_error_role``);
    ``rejected`` lists the others with a reason. Reply items the parser could not
    read (``claims["unparsed"]``) count as claimed and rejected. Dependencies are only located here;
    ``verify_dependencies`` resolves them once every module's facts exist.
    """
    index = SourceIndex(content)
    result = {key: [] for key in CLAIM_KEYS}
    rejected = []
    claimed = 0
    unparsed = claims.get("unparsed", 0) if isinstance(claims, dict) and isinstance(claims.get("unparsed"), int) else 0
    if unparsed:
        claimed += unparsed
        rejected.extend({"kind": "unparsed", "reason": "reply item that is not valid YAML"} for _ in range(unparsed))

    symbols = _claim_list(claims, "symbols")
    claimed += len(symbols)
    kept, symbol_rejects = _verify_symbols(symbols, index)
    result["symbols"] = kept
    rejected += symbol_rejects

    for item in _claim_list(claims, "dependencies"):
        claimed += 1
        target, evidence = _as_text(item.get("target")).strip(), _as_text(item.get("evidence"))
        matches = index.locate(evidence) if target else []
        if not matches:
            rejected.append({"kind": "dependency", "target": target, "evidence": evidence, "reason": "evidence not in source"})
            continue
        first, last, how = matches[0]
        text, truncated = index.excerpt(first, last, evidence)
        entry = {"target": target, "line": first + 1, **_end(first, last), "evidence": text, "match": how}
        result["dependencies"].append({**entry, "truncated": True} if truncated else entry)

    for key in ("config", "errors"):
        for item in _claim_list(claims, key):
            claimed += 1
            name, evidence = _as_text(item.get("name")).strip(), _as_text(item.get("evidence"))
            # A quote that opens a multi-line call (`parser.add_argument(`) also covers the call's lines when the
            # name is not on its own lines (`extended`)
            matches = []
            for first, last, how in index.locate(evidence) if name else []:
                if _names_in(index.text(first, last), name):
                    matches.append((first, last, how, False))
                    continue
                end = _call_span(index, first, last)
                if end > last and _names_in(index.text(first, end), name):
                    matches.append((first, end, how, True))
            if not matches:
                rejected.append({"kind": key, "name": name, "evidence": evidence, "reason": "name/evidence not in source"})
                continue
            # Of several places: the name used in code, then written as a whole string, then only mentioned in
            # prose; the quote's own lines before extended spans; for errors, raising before handling
            roles = {m: _error_role(index, m[0], m[1], name) for m in matches} if key == "errors" else {}
            matches.sort(key=lambda m: (_ROLE_RANK.get(roles.get(m), 0), _name_rank(index.text(m[0], m[1]), name), m[3]))
            first, last, how, extended = matches[0]
            text, truncated = index.excerpt(first, last, evidence)
            if extended and not _names_in(text, name):  # a long call: center the stored text on the name
                text, truncated = index.excerpt(first, last, name)
            entry = {"name": name, "line": first + 1, **_end(first, last), "evidence": text, "match": how}
            if key == "config":
                entry["kind"] = _as_text(item.get("kind")).strip() or "config"
            else:
                entry["role"] = roles[matches[0]]
            result[key].append({**entry, "truncated": True} if truncated else entry)

    # One fact quoted twice (a whole signature and its first line, an import and its block) is kept once; a
    # config key or error found both on a call's line and inside its extended span keeps the narrower place
    for key, fields in (("symbols", ("parent", "name")), ("dependencies", ("target",)), ("config", ("name",)), ("errors", ("name",))):
        seen, unique = set(), []
        for entry in result[key]:
            marker = (*(entry.get(field) for field in fields), entry["line"])
            if marker not in seen:
                seen.add(marker)
                unique.append(entry)
        if key in ("config", "errors"):
            narrow_first = sorted(unique, key=lambda e: e.get("end_line", e["line"]) - e["line"])
            kept_spans = []
            for entry in narrow_first:
                low, high = entry["line"], entry.get("end_line", entry["line"])
                if not any(other["name"] == entry["name"] and low <= other["line"] <= high for other in kept_spans):
                    kept_spans.append(entry)
            unique = [entry for entry in unique if any(entry is other for other in kept_spans)]
        claimed -= len(result[key]) - len(unique)
        result[key] = unique
    result["rejected"] = rejected
    result["claimed"] = claimed
    result["found"] = claimed - len(rejected)
    return result


def _verify_symbols(symbols: list[dict], index: SourceIndex) -> tuple[list, list]:
    """Locate each symbol's signature, members inside their parent.

    Every top-level symbol is placed first, then parents before their members. A member is searched
    from its parent's line to the next top-level symbol, so ``prep`` declared in ten classes of one file
    lands on the right line; failing that, file-wide, where a match counts only when its text names the
    parent (a Go receiver, a C++ ``Class::``) or the blocks around it name the parent (``_parent_verdict``:
    a Rust ``impl`` or Swift ``extension`` block far below the type), or — when the blocks cannot tell — the
    nearest class-like symbol declared above it is that parent (or there is none). A member signature matching several
    lines that no parent span tells apart is rejected; a top-level one (conditional definitions) is
    kept at its first line with ``ambiguous_lines``. Inside the span, too, a member is rejected when the
    blocks around it show it belongs elsewhere (``_parent_verdict``): the span of a class claimed above an
    unclaimed one runs on over the unclaimed class's methods.
    """
    kept, rejected, placed = [], [], {}
    # Top-level claims first: a member's span ends at the next top-level symbol, so all of them must be
    # known before any member is searched (claims come in file order, members right after their class)
    pending, unscoped = sorted(symbols, key=lambda item: bool(_as_text(item.get("parent")).strip())), False
    while pending:
        pending_names = {_as_text(item.get("name")).strip() for item in pending}
        waiting = []
        for item in pending:
            name, parent = _as_text(item.get("name")).strip(), _as_text(item.get("parent")).strip()
            if not unscoped and parent and parent != name and parent not in placed and parent in pending_names:
                waiting.append(item)
                continue
            signature = _as_text(item.get("signature"))
            matches, scoped = [], False
            tops = sorted(entry["line"] - 1 for entry in kept if not entry["parent"])
            containers = sorted((entry["line"] - 1, entry["name"]) for entry in kept if entry["kind"] in _CONTAINER_KINDS)
            if parent in placed:
                start = placed[parent]
                end = next((line for line in tops if line > start), None)
                matches = [
                    m
                    for m in index.locate(signature, start, end)
                    if name and _names_in(index.text(m[0], m[1]), name) and _parent_verdict(index, m, parent) is not False
                ]
                scoped = bool(matches)
            if not matches:
                matches = [m for m in index.locate(signature) if name and _names_in(index.text(m[0], m[1]), name)]
                if parent:
                    matches = [m for m in matches if _in_parent(index, m, parent, containers)]
            if not matches or (len(matches) > 1 and parent and not scoped):
                if not matches:
                    reason = "signature not in source" if not index.locate(signature) else "name not in its signature, or outside its parent"
                else:
                    reason = "signature matches several lines; the parent does not tell them apart"
                rejected.append({"kind": "symbol", "name": name, "parent": parent, "signature": signature, "reason": reason})
                continue
            first, last, how = matches[0]
            # A declaration quoted by its first lines (the prompt allows 3) runs on to the line closing its
            # parameter list, so the stored signature is complete
            last = _call_span(index, first, last)
            text, truncated = index.excerpt(first, last, signature)
            entry = {
                "name": name,
                "kind": _as_text(item.get("kind")).strip() or "symbol",
                "parent": parent,
                "visibility": _as_text(item.get("visibility")).strip() or None,
                "line": first + 1,
                **_end(first, last),
                "signature": text,
                "match": how,
            }
            if truncated:
                entry["truncated"] = True
            if len(matches) > 1:
                entry["ambiguous_lines"] = [m[0] + 1 for m in matches]
            kept.append(entry)
            placed.setdefault(name, first)
        unscoped = len(waiting) == len(pending)
        pending = waiting
    kept.sort(key=lambda entry: entry["line"])
    return kept, rejected


def _end(first: int, last: int) -> dict:
    """``{"end_line": n}`` (1-based) for a match spanning several lines, else nothing."""
    return {"end_line": last + 1} if last > first else {}


def _enclosing(containers: list[tuple[int, str]], line: int) -> str | None:
    """Name of the nearest class/struct/module-like symbol declared before *line*, if any."""
    names = [name for start, name in containers if start < line]
    return names[-1] if names else None


def _parent_verdict(index: SourceIndex, match: tuple, parent: str) -> bool | None:
    """Whether the blocks around a member match say it belongs to *parent*: True when its own text names the
    parent (a Go receiver, a C++ ``Class::``) or an enclosing line does (``class Foo:``, ``impl<T> Foo<T>``,
    ``impl Display for Foo {``, ``defmodule Shop.Cart do``), looking through control blocks, labels and nameless
    containers (``companion object {``, ``class << self``, ``typedef struct {``); False when a named container
    that is not the parent encloses it, or it sits in a top-level function; None when nothing can tell
    (unindented, or only statements above it — a column-0 heredoc line ends the chain)."""
    if parent in _words(index.text(match[0], match[1])):
        return True
    if not _indent(index.lines[match[0]], 8):
        return None
    for indent, text, kind, named in index.block_chain(match[0]):
        if _names_in(text, parent):
            return True
        if named:
            return False
        if not indent:
            return True if kind == "container" else False if kind == "function" else None
    return None


def _in_parent(index: SourceIndex, match: tuple, parent: str, containers: list) -> bool:
    """Whether a file-wide match of a member belongs to *parent* (see ``_verify_symbols``)."""
    verdict = _parent_verdict(index, match, parent)
    return verdict if verdict is not None else _enclosing(containers, match[0]) in (None, parent)


def _call_span(index: SourceIndex, first: int, last: int) -> int:
    """Last line of a match whose lines open more ``(`` / ``[`` than they close (a multi-line call such as
    ``parser.add_argument(`` ... ``)``, ``[`` lists): the line that closes them, at most ``_CALL_SPAN_LINES``
    further; *last* when balanced or never closed. A block's ``{`` does not count: a function or ``if``
    header is no evidence for what its body reads."""
    depth = 0
    for number in range(first, min(len(index.lines), last + 1 + _CALL_SPAN_LINES)):
        code = _STRING_RE.sub('""', index.lines[number])
        depth += code.count("(") + code.count("[") - code.count(")") - code.count("]")
        if number >= last and depth <= 0:
            return number
    return last


def _name_rank(text: str, name: str) -> int:
    """How a config/error match writes *name*: 0 in code (``os.environ.get(API_KEY)``, ``API_KEY = …``), 1 as a
    whole string literal (``"--mode"``), 2 only inside a longer string (another flag's help text)."""
    if _names_in(_STRING_RE.sub('""', text), name):
        return 0
    return 1 if any(m.group()[1:-1] == _nfc(name) for m in _STRING_RE.finditer(_nfc(text))) else 2


def _error_role(index: SourceIndex, first: int, last: int, name: str) -> str:
    """``raised``, ``caught`` or ``mentioned``: read on the first line of the match that names the error, from
    the text before the name (strings blanked) — a handler keyword after the last raise keyword means caught
    (``except (KeyError, X):``, ``} catch (e) {``, ``rescue X => e``, Kotlin ``try {…} catch (e: X)``, Dart
    ``} on X catch``), a raise keyword means raised (``} catch (e) { throw new X(…) }``, ``raise X(…)``,
    ``fmt.Errorf(…, X)``), neither (a definition, a return) means mentioned."""
    pattern = re.compile(r"(?<![\w$])" + re.escape(_nfc(name)) + r"(?![\w$])")
    for number in range(first, last + 1):
        code = _STRING_RE.sub('""', _nfc(index.lines[number]))
        found = pattern.search(code)
        if not found:
            continue
        head = code[: found.start()]
        handler = max((m.end() for m in _HANDLER_RE.finditer(head)), default=-1)
        if re.search(r"(?<![\w.$])on\s+$", head):
            handler = len(head)
        raiser = max((m.end() for m in _RAISE_RE.finditer(head)), default=-1)
        return "caught" if handler > raiser else "raised" if raiser >= 0 else "mentioned"
    return "mentioned"


# ---------------------------------------------------------------------------
# Completeness: lines that look like imports or declarations but no claim covers
# ---------------------------------------------------------------------------

# Words that start a declaration across languages (after modifiers), when followed by a name. Like
# _IMPORT_WORDS, only a hint: an uncovered line triggers a follow-up question, never a fact. Containers a
# reader does not look up by themselves (namespace, module, impl blocks, reopened classes) are left out.
_DECLARATION_WORDS = {
    "def", "class", "function", "func", "fun", "fn", "struct", "interface", "enum", "trait", "type", "typealias",
    "record", "object", "protocol", "extension", "macro", "sub", "procedure", "typedef", "defmodule", "defp",
    "defmacro", "defstruct", "defprotocol", "defimpl", "defguard", "defdelegate", "union", "newtype", "actor",
    "mixin", "contract", "service", "message", "given", "instance", "factory", "data",
}  # fmt: skip
# Declaration words that open a body a nested declaration belongs to (a function) rather than a container
_FUNCTION_WORDS = {"def", "function", "func", "fun", "fn", "sub", "procedure", "defp", "defmacro", "macro", "factory"}
_TOP_LEVEL_WORDS = {"const", "let", "var", "val", "local", "static", "global"}  # declarations only when unindented
_DECLARATION_MODIFIERS = _MODIFIERS | {
    "export", "async", "abstract", "final", "override", "sealed", "virtual", "extern", "inline", "open", "default",
    "unsafe", "partial", "readonly", "synchronized", "native", "suspend", "noinline", "lateinit", "lazy",
    "implicit", "companion", "fileprivate", "mutating", "convenience", "operator", "infix", "tailrec",
}  # fmt: skip
_CONTROL_WORDS = {"if", "for", "while", "switch", "return", "else", "do", "case", "catch", "when", "match", "elif", "unless", "until"}
# Block openers: a declaration inside a function body (a nested helper, a callback's closure) is local; inside
# a container (class, struct, impl, module, namespace …) it is a member; control blocks are looked through
_CONTAINER_WORDS = (_DECLARATION_WORDS - _FUNCTION_WORDS) | {"impl", "namespace", "module", "mod", "package"}
_BLOCK_CONTROL_WORDS = _CONTROL_WORDS | {
    "try",
    "except",
    "finally",
    "with",
    "loop",
    "foreach",
    "using",
    "lock",
    "begin",
    "rescue",
    "ensure",
    "defer",
    "select",
    "guard",
}
# A closure or block opening on the line: `() => {`, `function (req) {`, `lambda:`, `do |x|`, `{ |x|`, `fn(x) {`
_CLOSURE_RE = re.compile(r"=>|\bfunction\b|\blambda\b|\bdo\s*(?:\|[^|]*\|)?\s*$|\{\s*\|[^|]*\|\s*$|\bfn\s*\(|\bfunc\s*\(")
_NAMELESS_DECLARATIONS = {"defstruct", "defexception"}  # Elixir: `defstruct [:name, :email]`
# `Type name = …` / `Type name;` after modifiers on an unindented line: Dart / C-family typed top-level values
_TYPED_VALUE_RE = re.compile(r"^[A-Za-z_][\w.<>\[\],?]*\s+[A-Za-z_$][\w$]*\s*(?:=[^=]|;|$)")
_WORD_AT_RE = re.compile(r"([A-Za-z_]\w*)(\s+|\(|$)")
_ANNOTATIONS_RE = re.compile(r"^(?:@[\w.]+(?:\([^)]*\))?\s+)+")  # @objc, @Published, @testable, @Override
_PATH_TOKEN_RE = re.compile(r"[\w@$~-]+(?:(?:[./\\]|::)+[\w@$~*-]+)+|[\"'<`][^\"'<>`\s]+[\"'>`]")  # a.b, a/b, a::b, "x", <x>
# Unindented `type name(...)` ending the line with `{`, `)` or `) const {` (C-like function definitions); prose
# with a parenthesis mid-line does not end that way
_C_FUNCTION_RE = re.compile(
    r"^[A-Za-z_][\w\s\*&:<>,\[\]]*?\b[A-Za-z_][\w:~]*\s*\([^;]*\)\s*(?:(?:const|noexcept|override|final|async\*?|sync\*)\s*)*(?:->[^{]*)?\{?\s*$"
)  # `Future<void> fetch() async {`, `int size() const noexcept {`
_CONSTANT_RE = re.compile(r"^_*[A-Z][A-Z0-9_]*\s*(?::[^=]*)?=([^=].*)$")  # UPPER_CASE = ..., _PRIVATE_CONSTANT = ...
_SIGNATURE_RE = re.compile(r"^[a-z_][\w']*\s*::\s*\S")  # unindented Haskell-style type signature: parse :: String -> Expr
_SQL_CREATE_RE = re.compile(r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|INDEX|FUNCTION|PROCEDURE|TYPE|TRIGGER|SCHEMA)\b", re.IGNORECASE)
_EXPORTED_FUNCTION_RE = re.compile(r"^(?:module\.)?exports(?:\.\w+)?\s*=\s*(?:async\s+)?function\b")  # module.exports = function f(
_NOT_IMPORT_AFTER = set("=+-*/%|&>!,;)]}?:")  # `source = x`, `include += y`: an expression, not an import (`<` opens #include <x>)
# require('./x'), import('./x'), and Lua / Ruby's parenthesis-free require "x"
_IMPORT_CALL_RE = re.compile(r"(?<![\w.])(?:(?:require|require_relative|import)\s*\(\s*|(?:require|require_relative)\s+)[\"'`]")
# `[type] name(args)` with no `.`, `=` or `new` before the parenthesis: a method or function definition head
_METHOD_RE = re.compile(r"^(?!(?:new|return|throw|await|yield|else|delete|typeof)\b)[\w<>\[\],\s\*&:?]*?\b[A-Za-z_$][\w$]*\s*\(")
# Block delimiters, one-line string literals (skipped whole) and trailing comment markers after whitespace
_CODE_TOKEN_RE = re.compile(
    r"\"\"\"|'''|/\*|\"(?:\\.|[^\"\\])*(?:\"|$)|'(?:\\.|[^'\\])*(?:'|$)|`(?:\\.|[^`\\])*(?:`|$)|(?<=[\s;])(?:#|//|--(?=\s|$))"
)
_BLOCK_CLOSERS = {'"""': '"""', "'''": "'''", "/*": "*/"}


def _find_closer(line: str, closer: str, start: int) -> int:
    """Position of a block closer in *line* from *start*, -1 if none; a ``*/`` right after ``/`` is part of a
    glob (``build/*/``), not the end of a comment."""
    position = line.find(closer, start)
    while closer == "*/" and position > 0 and line[position - 1] == "/":
        position = line.find(closer, position + 1)
    return position


def _rfind_closer(line: str, closer: str) -> int:
    position = line.rfind(closer)
    while closer == "*/" and position > 0 and line[position - 1] == "/":
        position = line.rfind(closer, 0, position)
    return position


def code_view(lines: list[str]) -> list[str]:
    """The lines with comments and block strings blanked, for the hints only (line numbers unchanged).

    Block strings and comments (``\"\"\"`` / ``'''`` docstrings, ``/* ... */``) and trailing comments (``#``,
    ``//``, ``--`` after whitespace or ``;``) hold prose, usage examples and commented-out code: none of it is a
    declaration or import. A language-agnostic scan: delimiters inside a one-line string literal do not count
    (``'\"\"\"'``, ``"src/*"``), nor a ``/*`` right after a name (a glob: ``lib/*.sh``), nor an opener whose
    closer never follows in the file. A block string becomes ``""`` so ``HELP = \"\"\"...`` stays an
    assignment; lines starting with ``#`` or ``//`` are left to the line tests (``#include`` is an import)."""
    last = {}  # closer → (line, column) of its last occurrence
    for closer in set(_BLOCK_CLOSERS.values()):
        for number in range(len(lines) - 1, -1, -1):
            column = _rfind_closer(lines[number], closer)
            if column >= 0:
                last[closer] = (number, column)
                break
    view, closing = [], None
    for number, line in enumerate(lines):
        out, position = "", 0
        if closing:
            end = _find_closer(line, closing, 0)
            if end < 0:
                view.append("")
                continue
            position, closing = end + len(closing), None
        elif line.lstrip().startswith(("#", "//")):
            view.append(line)
            continue
        while True:
            match = _CODE_TOKEN_RE.search(line, position)
            if not match:
                out += line[position:]
                break
            token, start = match.group(), match.start()
            if token in ("#", "//", "--"):
                out += line[position:start]
                break
            closer = _BLOCK_CLOSERS.get(token)
            glob = token == "/*" and start and (line[start - 1].isalnum() or line[start - 1] in "_.*/$}\"')")  # lib/*.sh, "$OUT"/*
            if not closer or glob or last.get(closer, (-1, -1)) < (number, match.end()):
                out += line[position : match.end()]
                position = match.end()
                continue
            out += line[position:start] + ('""' if closer != "*/" else " ")
            end = _find_closer(line, closer, match.end())
            if end < 0:
                closing = closer
                break
            position = end + len(closer)
        view.append(out.rstrip())
    return view


def _lead(stripped: str) -> tuple[list[str], str | None, str, str]:
    """``(modifiers, first other word, separator after it, rest)`` of a line, annotations dropped."""
    text, modifiers = _ANNOTATIONS_RE.sub("", stripped.lstrip("$")), []
    while True:
        text = re.sub(r"^(\w+)\(\w+\)\s+", r"\1 ", text)  # private(set) var → private var
        lead = _WORD_AT_RE.match(text)
        if not lead:
            return modifiers, None, "", text
        word, separator = lead.group(1), lead.group(2)
        rest = text[lead.end() :]
        is_modifier = word in _DECLARATION_MODIFIERS or (word == "case" and re.match(r"(?:class|object)\b", rest))
        if is_modifier and separator and not separator.strip():
            modifiers.append(word)
            text = rest
            continue
        return modifiers, word, separator, rest


def declaration_like(line: str) -> bool:
    """Whether a source line looks like a declaration a reader would look up (language-agnostic hint)."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return stripped.startswith(("#define ", "#macro "))
    if not (stripped[0].isalpha() or stripped[0] in "_@$"):  # comments, closers, strings, operators
        return False
    unindented = line[:1] not in (" ", "\t")
    constant = _CONSTANT_RE.match(stripped)
    if constant and not re.search(r"(?:^|\s)[a-z]+\s+[a-z]+[^()\[\]{}]*\.$", constant.group(1)):  # not prose: `X=off disables it.`
        return True
    if _SQL_CREATE_RE.match(stripped) or _EXPORTED_FUNCTION_RE.match(stripped):
        return True
    if unindented and (_C_FUNCTION_RE.match(stripped) or _SIGNATURE_RE.match(stripped)):
        return True
    modifiers, word, separator, rest = _lead(stripped)
    if word is None and modifiers and _CONSTANT_RE.match(rest):  # readonly CONFIG_DIR=/etc/app, export API_URL=…
        return True
    if word is None or word in _CONTROL_WORDS:
        return bool(modifiers) and _METHOD_RE.match(rest) is not None
    # a name next (or a Go receiver: `func (c *Cache) Put(`)
    names_next = bool(separator) and not separator.strip() and bool(re.match(r"[A-Za-z_$(]", rest))
    if (word in _DECLARATION_WORDS and names_next) or (word in _NAMELESS_DECLARATIONS and separator):
        return True
    if unindented and word in _TOP_LEVEL_WORDS and names_next:
        return True
    text = f"{word}{separator}{rest}"
    if unindented and modifiers and _TYPED_VALUE_RE.match(text):  # final String apiUrl = 'x';
        return True
    if modifiers:  # public void run(, public Ledger(string n)
        return _METHOD_RE.match(text) is not None
    # `type name(...) {` with no modifier: a definition head, not a call taking a callback (`describe('x', () => {`,
    # `useEffect(() => {`), a chained call or a match arm (`Err(err) => Response {`)
    if not text.rstrip().endswith("{") or " => " in text or _METHOD_RE.match(text) is None:
        return False
    inside = text[text.find("(") + 1 : text.rfind(")")] if ")" in text else ""
    return not re.search(r"=>|->|[\"'`]|\w\s*\(", inside)


def import_statement_like(line: str) -> bool:
    """An import-like line that is a statement, not a comment, call, assignment or expression (``# from ...``,
    ``source = x``, ``open(path)``, ``using (var r = ...)``) nor a declaration (``export function f``) nor a
    block opener (``import (``, ``import {``); ``export`` only with ``from`` or a quoted specifier. A
    ``require('x')`` / ``import('x')`` call anywhere in the line and a shell ``. path`` also count."""
    stripped = _ANNOTATIONS_RE.sub("", line.strip())  # @testable import X
    if stripped.startswith(("//", "/*", "*", "--")):  # comments, a Lua / SQL `--` line too
        return False
    if stripped.startswith("#"):  # only a preprocessor include (`#include "x.h"`, `# include <y>`, `#import`)
        if not re.match(r"#\s*(?:include|import)\s*[<\"]", stripped):  # not a commented-out `# import os`
            return False
        stripped = "#" + stripped[1:].lstrip()
    if stripped.startswith(("'", '"', "`")):
        return False
    strings = [m.span() for m in _STRING_RE.finditer(stripped)]
    if any(not any(low <= call.start() < high for low, high in strings) for call in _IMPORT_CALL_RE.finditer(stripped)):
        return True  # require('x') / import('x') in code, not in a message such as "call require('x') first"
    if re.match(r"^\.\s+[\"'$./\w]", stripped):  # shell: . ./lib/env.sh
        return True
    if not _import_like(stripped):
        return False
    words = _words(stripped.lstrip("#@"))
    while words and words[0] in _MODIFIERS:
        words = words[1:]
    after = stripped.lstrip("#@").split(words[0], 1)[1].lstrip()
    if not after or after in ("(", "{", "["):
        return False
    if after[0] == "*" and words[0] in ("import", "export"):  # import * as x from …, export * from …
        return re.match(r"\*\s*(?:as\s+[\w$]+\s+)?from\b", after) is not None
    if after[0] in _NOT_IMPORT_AFTER:
        return False
    julia_relative = words[0] in ("using", "import") and re.match(r"\.+[A-Za-z_]", after)  # using .Cart
    if after[0] == "." and words[0] != "from" and after[1:2] not in ("/", ".") and not julia_relative:  # import.meta: attribute access
        return False
    if after[0] == "(" and (
        words[0] not in ("require", "require_once", "include", "include_once", "import", "load", "source", "library", "use")
        or not re.match(r"\(\s*[\"'`\w$./@~]", after)
    ):  # a call form needs an argument naming what it loads: library(dplyr), require_once('x.php'), not load().then(
        return False
    relative_import = words[0] == "from" and " import " in f" {after} "  # from .models import A, B, C, D, E
    if len(_words(after)) > 6 and not _PATH_TOKEN_RE.search(after) and not relative_import:  # prose that starts with `source`, `use`, …
        return False
    if words[0] == "from" and re.match(r"[\w.]+,", after):  # from here on, …
        return False
    if re.search(r"[A-Za-z]\.$", after) and len(_words(after)) >= 3 and not re.search(r"[\"'<`/;]", after):  # a sentence
        return False
    return words[0] != "export" or " from " in f" {stripped} " or after[:1] in ("'", '"')


def import_block_lines(lines: list[str]) -> set[int]:
    """0-based lines inside an ``import ( ... )`` block (Go): bare quoted paths with no keyword of their own."""
    found, inside = set(), False
    for number, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^import\s*\($", stripped):
            inside = True
        elif inside and stripped == ")":
            inside = False
        elif inside and _GO_BLOCK_LINE_RE.match(line):
            found.add(number)
    return found


def _indent(line: str, tab: int = 4) -> int:
    expanded = line.expandtabs(tab)
    return len(expanded) - len(expanded.lstrip())


def _block_kind(line: str) -> str | None:
    """What a line opens for the lines indented under it: ``function``, ``container``, ``control`` or
    ``other`` (an object literal, a decorator, a call's arguments); None for a line that opens nothing
    itself — only brackets, or a closer continuing a construct (``) -> None:``, ``} else {``, ``end``)."""
    stripped = line.strip()
    if not re.search(r"\w", stripped) or stripped[0] in ")]}" or re.fullmatch(r"end\b\W*", stripped):
        return None
    _modifiers, word, separator, rest = _lead(stripped)
    if word in _FUNCTION_WORDS:
        return "function"
    if word in _CONTAINER_WORDS:
        return "container"
    if word in _BLOCK_CONTROL_WORDS:
        return "control"
    if _CLOSURE_RE.search(stripped) or (word and _METHOD_RE.match(f"{word}{separator}{rest}") and re.search(r"[)\]{:]\s*$", stripped)):
        return "function"  # a callback (describe('x', () => {), a method head (public void run() {, int main(void))
    return "other"


def _nameless(text: str) -> bool:
    """A container line that declares no name: ``companion object {``, ``class << self``, ``typedef struct {``,
    ``union {`` (generics after the keyword skipped: ``impl<T> Store<T>`` is named)."""
    rest = _ANNOTATIONS_RE.sub("", text.strip())
    while True:
        rest = re.sub(r"^<[^<>]*>\s*", "", rest)
        word = re.match(r"([A-Za-z_]\w*)\s*", rest)
        if word and (word.group(1) in _CONTAINER_WORDS or word.group(1) in _DECLARATION_MODIFIERS):
            rest = rest[word.end() :]
            continue
        return not re.match(r"[A-Za-z_$]", rest)


def _block_chains(lines: list[str]) -> list[tuple]:
    """Per line, the lines of the blocks it sits in, innermost first: ``(indent, text, kind, named)`` with
    ``kind`` from ``_block_kind`` and ``named`` for a container that declares a name. One pass over
    ``code_view`` (block strings blanked) with a stack of open blocks by indentation, tabs as 8 columns (git's
    width); blank and comment lines, closers (``) : Base() {``, ``} else {``) and labels (``public slots:``,
    ``where``, ``private``) neither open nor close a block."""
    chains, stack = [], []
    for text in code_view(lines):
        indent = _indent(text, 8)
        chains.append(tuple(entry for entry in reversed(stack) if entry[0] < indent))
        if not re.search(r"\w", text) or _COMMENT_START_RE.match(text):
            continue
        kind = _block_kind(text)
        label = _LABEL_RE.fullmatch(text)
        if kind is None or (label and kind != "container" and (label.group(1) or label.group(2)) not in _BLOCK_CONTROL_WORDS):
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, text, kind, kind == "container" and not _nameless(text)))
    return chains


def enclosing_blocks(lines: list[str]) -> list[str | None]:
    """Per line, the kind (``_block_kind``) of the nearest less-indented line above that opens a block,
    looking through control blocks: ``function`` for a nested helper or local, ``container`` for a member,
    None at the top level. One pass with a stack of open blocks; indentation is the only structure used."""
    kinds, stack = [], []  # stack of (indent, kind)
    for line in lines:
        kind = _block_kind(line) if line.strip() else None
        if kind is None:
            kinds.append(None)
            continue
        indent = _indent(line)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        kinds.append(next((k for _i, k in reversed(stack) if k != "control"), None))
        stack.append((indent, kind))
    return kinds


def completeness_hints(content: str, checked: dict, claims: dict | None = None) -> dict:
    """Lines that look like imports or declarations (1-based), and those no located claim of the matching
    kind covers.

    Returns ``{"import_lines", "declaration_lines", "uncovered"}``; ``uncovered`` is what a follow-up asks
    about. Comments and block strings are left out (``code_view``), and so are declarations inside a
    function body or callback (``enclosing_blocks``): locals the prompt skips. Import lines are covered by dependency claims, declaration lines by symbol claims (a config or
    dependency fact quoting a declaration does not report the declared symbol). A symbol claim covers the
    lines it was located on (``ambiguous_lines`` too): ``def run(self)`` in two classes is two symbols. A
    dependency claim also covers every line with the same text as its match or its quote in *claims* (one
    import repeated inside several functions is one fact).
    """
    lines = split_lines(_nfc(content))
    view = code_view(lines)
    imports = {n for n, line in enumerate(view) if import_statement_like(line)} | import_block_lines(view)
    enclosing = enclosing_blocks(view)
    declarations = {n for n, line in enumerate(view) if n not in imports and enclosing[n] != "function" and declaration_like(line)}

    import_numbers, import_texts = set(), set()
    for entry in checked.get("dependencies", []):
        span = range(entry["line"] - 1, entry.get("end_line", entry["line"]))
        import_numbers.update(span)
        import_texts.update(_collapse(lines[n]) for n in span if n < len(lines))
    import_texts.update(_collapse(_as_text(item.get("evidence"))) for item in _claim_list(claims or {}, "dependencies"))
    symbol_numbers = set()
    for entry in checked.get("symbols", []):
        symbol_numbers.update(range(entry["line"] - 1, entry.get("end_line", entry["line"])))
        symbol_numbers.update(n - 1 for n in entry.get("ambiguous_lines", []))
    uncovered = {n for n in imports if n not in import_numbers and _collapse(lines[n]) not in import_texts}
    uncovered |= {n for n in declarations if n not in symbol_numbers}
    return {
        "import_lines": sorted(n + 1 for n in imports),
        "declaration_lines": sorted(n + 1 for n in declarations),
        "uncovered": sorted(n + 1 for n in uncovered),
    }


def unexplained_names(content: str, source_path: str, depends_on: list[dict], table) -> list[dict]:
    """Names that exactly one other module defines (``ModuleTable.symbol_owner``), used in this source's
    code, with no verified dependency on that module: ``[{"name", "module"}]``. A recall hint for
    same-package and same-namespace use without an import line (Go, Java, Kotlin, C#, Ruby, Elixir …).
    Comments and string literals do not count (interpolations ``${x}``, ``#{x}``, ``\\(x)`` and ``$VAR`` do),
    nor attribute accesses (``x.get()`` uses ``x``) and names the file binds itself: ``let``/``var``/``val``/
    ``const``/``for`` bindings incl. destructuring, statement-start assignments (``a, b := …``) and keyword
    arguments — a type written after ``:`` is a use, not a binding. A dotted name also matches its sub-chains
    (``Shop.Cart.add`` uses ``Shop.Cart`` and ``Cart``)."""

    def code_of(line: str) -> str:
        if re.match(r"\s*(?://|#(?:[\s!#]|$)|--(?:\s|$))", line):
            return ""  # a comment line (a Swift `#expect(`, a JS `#cache =` or a C `#include` stays)

        def keep_interpolations(literal):
            parts = [part for group in _INTERPOLATION_RE.findall(literal.group()) for part in group if part]
            if literal.group()[0] == '"':
                parts += ["$" + name for name in _SHELL_VAR_RE.findall(literal.group())]
            return " " + " ".join(parts) + " "

        return _STRING_RE.sub(keep_interpolations, line)

    code = "\n".join(code_of(line) for line in code_view(split_lines(_nfc(content))))
    bound = set()
    for pattern in (_KEYWORD_BINDS_RE, _LINE_BINDS_RE, _KWARG_BINDS_RE):
        for match in pattern.finditer(code):
            bound.update(name.strip() for name in match.group(1).split(","))
    used = set(_FIRST_NAME_RE.findall(code)) | set(_SHELL_VAR_RE.findall(code))
    # Sub-chains only as long as a dotted defined name (a chain of n parts has n² sub-chains)
    lengths = {name.count(".") + 1 for name in table.symbol_owner if "." in name}
    dotted = set()
    for chain in _DOTTED_RE.findall(code):
        parts = chain.split(".")
        used.update(part for part in parts[1:] if part[:1].isupper())  # Acme.Billing.Invoice: a namespace path
        dotted.update(".".join(parts[i : i + size]) for size in lengths for i in range(len(parts) - size + 1))
    linked = {edge["module"] for edge in depends_on}
    own = table.all_symbols.get(source_path, set())
    found = []
    for name, module in sorted(table.symbol_owner.items()):
        hit = (name in dotted or name.split(".")[-1] in used) if "." in name else name in used
        if module != source_path and module not in linked and name not in own and name not in bound and hit:
            found.append({"name": name, "module": module})
    return found


# Fields that identify a claim: a follow-up restating a fact with another summary or kind is the same fact
_IDENTITY_FIELDS = {
    "symbols": ("parent", "name", "signature"),
    "dependencies": ("target", "evidence"),
    "config": ("name", "evidence"),
    "errors": ("name", "evidence"),
}


def merge_claims(first: dict, second: dict) -> dict:
    """Union of two replies' claims (first pass + follow-up), duplicates dropped (same identity fields, first
    kept); ``unparsed`` added up."""
    merged = {}
    for key in CLAIM_KEYS:
        seen, items = set(), []
        for item in [*_claim_list(first or {}, key), *_claim_list(second or {}, key)]:
            marker = tuple(_collapse(_as_text(item.get(field))) for field in _IDENTITY_FIELDS[key])
            if marker not in seen:
                seen.add(marker)
                items.append(item)
        merged[key] = items
    merged["unparsed"] = (first or {}).get("unparsed", 0) + (second or {}).get("unparsed", 0)
    return merged


# ---------------------------------------------------------------------------
# Manifests: names under which the project's own code is imported
# ---------------------------------------------------------------------------

MANIFEST_KEYS = ("provides", "aliases")
# Keys whose value is the name a manifest declares (`"name": "@acme/api"`, `name = "shop-core"`, `module
# example.com/shop`, `<artifactId>shop</artifactId>`, `app: :shop`). A name written as a key or list item
# (`"@acme/api": "^1.2.0"`, `shop-core = { path = ... }`) is a dependency, not a declaration. A hint list
# like _IMPORT_WORDS, broad across manifest formats.
_NAME_KEYS = {
    "name", "module", "package", "artifactid", "groupid", "assemblyname", "rootnamespace", "packageid",
    "library", "crate", "app", "project", "modulename", "bundle",
}  # fmt: skip
# Keys whose value is an entry file (`"main": "src/index.ts"`, `path = "src/lib.rs"`, `"exports"`); a path in a
# script line (`"start": "tsx src/app/main.ts"`) is not an entry
_ENTRY_KEYS = {"main", "module", "exports", "types", "typings", "entry", "bin", "lib", "path", "browser", "source", "import", "require"}


def normalize_name(text: str) -> str:
    """Case-folded, ``-`` as ``_``: package, crate and distribution names compare equal across spellings
    (``shop-core`` in Cargo.toml, ``shop_core`` in ``use shop_core::store``)."""
    return _nfc(text).strip().casefold().replace("-", "_")


def _name_segments(text: str) -> list[str]:
    return [part for part in re.split(r"::|[./\\:]+", normalize_name(text)) if part]


def verify_manifest_claims(claims: dict, content: str, manifest_path: str) -> dict:
    """Check one manifest's ``provides`` / ``aliases`` claims against its text.

    A name, alias or target counts only when the quoted line is in the file and contains it verbatim; an
    ``entry`` or ``base`` the file does not contain is dropped (the name stays). Returns ``{"provides",
    "aliases", "rejected", "claimed", "found"}``; kept entries carry the 1-based ``line``.
    """
    index = SourceIndex(content)
    flat = _collapse(content)
    result = {"provides": [], "aliases": [], "rejected": []}
    unparsed = claims.get("unparsed", 0) if isinstance(claims, dict) and isinstance(claims.get("unparsed"), int) else 0
    claimed = unparsed
    result["rejected"].extend({"kind": "unparsed", "reason": "reply item that is not valid YAML"} for _ in range(unparsed))
    for item in _claim_list(claims, "provides"):
        claimed += 1
        name, evidence = _as_text(item.get("name")).strip(), _as_text(item.get("evidence"))
        matches = [m for m in (index.locate(evidence) if name else []) if _collapse(name) in _collapse(index.text(m[0], m[1]))]
        if not matches:
            result["rejected"].append({"kind": "provides", "name": name, "evidence": evidence, "reason": "name/evidence not in the manifest"})
            continue
        line = _collapse(index.text(matches[0][0], matches[0][1]))
        if not _declares_name(line, name):
            result["rejected"].append(
                {"kind": "provides", "name": name, "evidence": evidence, "reason": "the line does not declare the name (a dependency?)"}
            )
            continue
        entry = _as_text(item.get("entry")).strip()
        kept = {"name": name, "line": matches[0][0] + 1}
        if entry and any(_declares_name(line_text, entry, _ENTRY_KEYS) for line_text in index.collapsed if _collapse(entry) in line_text):
            kept["entry"] = entry
        result["provides"].append(kept)
    for item in _claim_list(claims, "aliases"):
        claimed += 1
        alias, target, evidence = (_as_text(item.get(key)).strip() for key in ("alias", "target", "evidence"))
        matches = [
            m
            for m in (index.locate(evidence) if alias and target else [])
            if _collapse(alias) in _collapse(index.text(m[0], m[1])) and _collapse(target) in _collapse(index.text(m[0], m[1]))
        ]
        if not matches:
            result["rejected"].append(
                {"kind": "aliases", "alias": alias, "evidence": evidence, "reason": "alias/target/evidence not in the manifest"}
            )
            continue
        base = _as_text(item.get("base")).strip()
        kept = {"alias": alias, "target": target, "line": matches[0][0] + 1}
        if base and _collapse(base) in flat:
            kept["base"] = base
        result["aliases"].append(kept)
    result["claimed"] = claimed
    result["found"] = claimed - len(result["rejected"])
    return result


def _declares_name(line: str, name: str, keys: set | None = None) -> bool:
    """Whether a naming key (``_NAME_KEYS``, or *keys*) comes right before the name on the line, as its value,
    and not inside a nested dependency value (``u = { package = "shop-utils" }``, ``project(':core')``)."""
    before = line.split(_collapse(name), 1)[0]
    words = _words(before)[-3:]
    key_at = max((before.rfind(word) for word in words if word.casefold() in (keys or _NAME_KEYS)), default=-1)
    return key_at >= 0 and not re.search(r"[{(]", before[:key_at])


def manifest_rules(manifests: dict) -> tuple[list, list]:
    """Verified manifest claims → ``(packages, aliases)`` for ``ModuleTable``.

    Packages: ``{"segments", "name", "dir", "entry"}`` (entry root-relative or None), longest name first.
    Aliases: ``{"prefix", "template", "mode", "dir"}`` with ``mode`` ``star`` (``@lib/*`` → prefix ``@lib/``,
    the template's ``*`` takes the rest), ``prefix`` (a key ending in ``/``: import maps, ``@/``) or
    ``exact`` (matches the key or ``key/…``); ``dir`` is the declaring manifest's directory, the alias's
    scope. Workspace globs (``packages/*``), package-relative export keys (``./button``) and catch-all keys
    (``*``) are left out: none of them is a name code imports by."""
    packages, aliases = [], []
    for path, verified in (manifests or {}).items():
        directory = posixpath.dirname(path)
        for provided in verified.get("provides", []):
            if "*" in provided["name"]:
                continue
            entry = provided.get("entry")
            entry_path = posixpath.normpath(posixpath.join(directory, entry)) if entry else None
            packages.append({"segments": _name_segments(provided["name"]), "name": provided["name"], "dir": directory, "entry": entry_path})
        for alias in verified.get("aliases", []):
            key = alias["alias"]
            if key.startswith(("./", "../")) or not key.split("*", 1)[0]:
                continue
            mode = "star" if "*" in key else "prefix" if key.endswith("/") else "exact"
            template = posixpath.normpath(posixpath.join(directory, alias.get("base") or ".", alias["target"]))
            aliases.append({"prefix": key.split("*", 1)[0], "template": "" if template == "." else template, "mode": mode, "dir": directory})
    packages.sort(key=lambda package: -len(package["segments"]))
    return packages, aliases


# ---------------------------------------------------------------------------
# Cross-module resolution (needs every module's symbols)
# ---------------------------------------------------------------------------


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _segments(path: str) -> list[str]:
    return [part for part in os.path.splitext(path)[0].split("/") if part]


def _is_relative(target: str) -> bool:
    return target.replace("\\", "/").startswith(("./", "../"))


class ModuleTable:
    """Documented modules for resolving dependency targets: paths, stems, directories, owned names."""

    def __init__(self, paths: list[str], symbols_by_path: dict, contents: dict | None = None, manifests: dict | None = None):
        """*symbols_by_path*: ``{path: [{"name", "kind", ...}, ...]}`` (verified symbols). Every symbol but a
        method owns its module (classes, functions, constants, also inside a module or namespace): a
        method name like ``get`` or ``to_h`` is called on objects of many types and proves nothing about
        which file a line uses. *manifests*: ``{manifest path: verify_manifest_claims result}``."""
        self.paths = list(paths)
        self.contents = contents or {}
        self.packages, self.aliases = manifest_rules(manifests)
        self.segments = {path: _segments(path) for path in self.paths}
        self.extensions = {os.path.splitext(path)[1] for path in self.paths if os.path.splitext(path)[1]}
        self.by_dir = defaultdict(list)
        for path in self.paths:
            self.by_dir[posixpath.dirname(path)].append(path)
        owners = defaultdict(set)
        self.top_symbols, self.all_symbols = {}, {}
        for path, symbols in symbols_by_path.items():
            self.all_symbols[path] = {symbol["name"] for symbol in symbols}
            self.top_symbols[path] = {symbol["name"] for symbol in symbols if symbol.get("kind") not in _OWNER_EXCLUDED_KINDS}
            for name in self.top_symbols[path]:
                if len(name) >= 3:
                    owners[name].add(path)
        self.symbol_owner = {name: next(iter(paths)) for name, paths in owners.items() if len(paths) == 1}
        self.owned = defaultdict(set)
        for name, path in self.symbol_owner.items():
            self.owned[path].add(name)
        for package in self.packages:
            package["extensions"] = {os.path.splitext(path)[1] for path in self.paths if not package["dir"] or path.startswith(package["dir"] + "/")}

    def normalize(self, target: str) -> tuple[list[str], str]:
        """``(segments, extension)`` of a target as written: ``utils.output``, ``./client``, ``@/http``,
        ``crate::store::Repo``, ``com.acme.billing.*``, ``App\\Db`` and ``net/socket.h`` all become segment
        lists; the extension is kept only when it is one of the documented modules' extensions. Parts
        that are not names (``{Repo, StoreError}`` of a grouped import) are dropped."""
        text = target.strip().strip("\"'`<>()[];,")
        for prefix in ("@/", "~/", "$/"):
            text = text.removeprefix(prefix)
        ext = os.path.splitext(text)[1]
        if ext in self.extensions:
            text = text[: -len(ext)]
        else:
            ext = ""
        text = text.replace("::", "/").replace("\\", "/").replace(".", "/")
        parts = [part.strip() for part in text.split("/")]
        return [part for part in parts if part and part not in ("*", "crate", "super", "self") and _SEGMENT_RE.match(part)], ext

    def _suffix_hits(self, tail: list[str], ext: str, source_path: str) -> list[str]:
        """Modules whose path (extension dropped) ends with *tail*; case-insensitively only when the exact case
        finds none. Of several hits, the only one in the source's own directory wins (``#include "config.h"``)."""
        for fold in (str, str.casefold):
            wanted = [fold(part) for part in tail]
            hits = [
                path
                for path in self.paths
                if path != source_path and (not ext or path.endswith(ext)) and [fold(part) for part in self.segments[path][-len(tail) :]] == wanted
            ]
            if len(hits) > 1:
                near = [path for path in hits if posixpath.dirname(path) == posixpath.dirname(source_path)]
                if len(near) == 1:
                    return near
            if hits:
                return hits
        return []

    def _index_file(self, directory: str) -> str | None:
        members = {_stem(path): path for path in self.by_dir.get(directory, [])}
        return next((members[stem] for stem in _INDEX_STEMS if stem in members), None)

    def _resolve_relative(self, target: str, source_path: str, source_words: set) -> tuple[list[str], str] | None:
        """``./x``, ``../x`` and leading-dot modules (``.models``, ``..core.engine``) against the source's directory.

        ``None`` means "no file-relative match": a ``./`` path then falls back to the project-wide search
        (shell ``source ./lib.sh`` and R ``source()`` resolve against the working directory)."""
        text = target.strip().strip("\"'`<>()[];,").replace("\\", "/")
        parent = re.match(r"^super(?:::(.*))?$", text)
        if parent:  # `super` names the parent module: the directory's index file, or one level up from an index file
            directory = posixpath.dirname(source_path)
            if _stem(source_path) in _INDEX_STEMS:
                directory = posixpath.dirname(directory)
            rest = [part for part in (parent.group(1) or "").split("::") if part and _SEGMENT_RE.match(part)]
            for size in range(len(rest), 0, -1):
                base = posixpath.join(directory, *rest[:size])
                hits = [path for path in self.paths if path != source_path and os.path.splitext(path)[0] == base]
                if len(hits) == 1:
                    return hits, "path"
            index_file = self._index_file(directory)
            return ([index_file], "package") if index_file and index_file != source_path else ([], "external")
        dots = re.match(r"^(\.+)(\w[\w.]*)$", text)
        if dots:
            text = "../" * (len(dots.group(1)) - 1) + "./" + dots.group(2).replace(".", "/")
        if not text.startswith(("./", "../")):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), text))
        resolved = self._resolve_rooted(base, source_path, source_words)
        if resolved is not None:
            return resolved
        if dots:
            return [], "external"  # a leading-dot module path is always file-relative
        return None

    def _resolve_rooted(self, base: str, source_path: str, source_words: set) -> tuple[list[str], str] | None:
        """A project-root-relative path: the file with any extension (``./types`` → ``types.d.ts`` too), else
        the directory (its index file and the files whose names the source uses); None when neither."""
        base = "" if base in (".", "") else base
        stem_match = [path for path in self.paths if path != source_path and (os.path.splitext(path)[0] == base or path == base)]
        if not stem_match:  # every extension dropped
            stem_match = [
                path
                for path in self.paths
                if path != source_path and posixpath.join(posixpath.dirname(path), posixpath.basename(path).split(".")[0]) == base
            ]
        if len(stem_match) == 1:
            return stem_match, "path"
        if not stem_match and base in self.by_dir:  # a directory: its index file and the files whose names the source uses
            index_file = self._index_file(base)
            used = [
                path for path in self.by_dir[base] if path != source_path and (path == index_file or self.used_names(path, source_path, source_words))
            ]
            if used:
                return used, "package"  # the evidence names the directory, not a file in it
        return None

    def resolve_manifest(self, target: str, source_path: str, source_words: set, prefer_local: bool = False) -> tuple[list[str], str] | None:
        """A target that starts with a declared path alias or package name → ``(modules, written prefix)``.

        File-relative targets (``./x``, ``../x``, ``.models``) never match: they resolve against the source's
        directory. With *prefer_local* (languages without the relative-import convention) a bare name that is
        a file or directory next to the source is local too (Rust ``mod store;``, Python ``import config``).
        A URI scheme is dropped first (``package:shop/x.dart``, ``jsr:@std/path``, ``node:fs``).

        Aliases apply below the directory of the manifest that declares them, deepest first, then longest
        prefix: ``@lib/*`` → ``src/lib/*`` (the ``*`` takes the rest; ``#db/*`` → ``src/db/*.ts``), a key
        ending in ``/`` is a prefix, any other key matches exactly or as ``key/…``. Packages match by name
        segments, case-folded with ``-`` as ``_`` (``shop_core::store`` for ``shop-core``), only from sources
        in a language the package holds: no rest → the declared entry, else an index file of the package
        directory (or its ``src``, ``lib`` or name directory), else its files whose names the source uses; a
        rest → a file or directory under the package ending with it (exact case, else case-insensitive),
        else — for a one-part rest the package root re-exports (its root file names it) — the root, like a
        barrel import, else a name only a file under the package defines. Every package whose name matches is
        tried, longest first. An alias or package that resolves nothing falls through to the next rule and
        to general resolution. ``([], "")`` (external) for a multi-part target sharing a declared multi-part
        name's first segment that nothing in the project matches (``example.com/other/store``), and, once
        manifests are known, a sigil-led name (``@scope/pkg``, ``#x``) nothing declares. None when no rule applies.
        """
        text = re.sub(r"^[A-Za-z][\w+.-]*:(?![/:\\])", "", target.strip().strip("\"'`<>()[];,"))
        if not text or text.startswith(("./", "../", ".\\", "..\\")) or re.match(r"^\.+\w", text):
            return None
        written = [part for part in re.split(r"::|[./\\:]+", _nfc(text).strip()) if part]
        source_dir = posixpath.dirname(source_path)
        if prefer_local and len(written) == 1 and self._resolve_rooted(posixpath.join(source_dir, written[0]), source_path, source_words):
            return None
        in_scope = [alias for alias in self.aliases if not alias["dir"] or source_path.startswith(alias["dir"] + "/")]
        for alias in sorted(in_scope, key=lambda alias: (-alias["dir"].count("/") - bool(alias["dir"]), -len(alias["prefix"]))):
            prefix, template, mode = alias["prefix"], alias["template"], alias["mode"]
            if mode == "exact":
                if text != prefix and not text.startswith(prefix + "/"):
                    continue
                rest = text[len(prefix) :].lstrip("/")
            elif not text.startswith(prefix):
                continue
            else:
                rest = text[len(prefix) :]
            if "*" in template:
                base = posixpath.normpath(template.replace("*", rest, 1))
            else:
                base = posixpath.normpath(posixpath.join(template, rest)) if rest else template
            resolved = self._resolve_rooted(base, source_path, source_words)
            if resolved:
                return resolved[0], prefix
        segments = _name_segments(text)
        extension = os.path.splitext(source_path)[1]
        for package in self.packages:
            if package["segments"] and segments[: len(package["segments"])] == package["segments"] and extension in package["extensions"]:
                found = self._resolve_in_package(package, written[len(package["segments"]) :], source_path, source_words)
                if found:
                    return found, package["name"]
        if len(segments) > 1 and any(len(p["segments"]) > 1 and p["segments"][0] == segments[0] for p in self.packages):
            if self.namespace_members(text, source_path, source_words) or self._matches_whole(text, source_path):
                return None  # a sibling namespace or module of the same organization that no manifest declares
            return [], ""
        if (self.packages or self.aliases) and text[:1] in ("@", "#", "~", "$"):  # a scoped or aliased name nothing declares
            return [], ""
        return None

    def _matches_whole(self, target: str, source_path: str) -> bool:
        """Whether a documented file or directory path ends with every segment of the target (Maven
        ``com.acme.shipping.Label`` → ``…/com/acme/shipping/Label.java``): a match that drops none of it."""
        parts, _ = self.normalize(target)
        return bool(parts) and (
            any(path != source_path and self.segments[path][-len(parts) :] == parts for path in self.paths)
            or any(d.split("/")[-len(parts) :] == parts for d in self.by_dir if d)
        )

    def _resolve_in_package(self, package: dict, rest: list[str], source_path: str, source_words: set) -> list[str]:
        directory = package["dir"]
        under = [path for path in self.paths if path != source_path and (not directory or path.startswith(directory + "/"))]
        root = self._package_root(package, under, source_path, source_words)
        if not rest:
            return root
        for size in range(len(rest), 0, -1):
            tail = rest[:size]
            for fold in (str, str.casefold):
                wanted = [fold(part) for part in tail]
                hits = [path for path in under if [fold(part) for part in self.segments[path][-len(tail) :]] == wanted]
                if len(hits) == 1:
                    return hits
                dirs = [
                    d
                    for d in self.by_dir
                    if (not directory or d == directory or d.startswith(directory + "/"))
                    and [fold(part) for part in d.split("/")[-len(tail) :]] == wanted
                ]
                if len(dirs) == 1:
                    index_file = self._index_file(dirs[0])
                    used = [
                        path
                        for path in self.by_dir[dirs[0]]
                        if path != source_path and (path == index_file or self.used_names(path, source_path, source_words))
                    ]
                    if used:
                        return used
                if hits or dirs:
                    break
        if len(rest) == 1 and len(root) == 1 and rest[0] in _words(self.contents.get(root[0], "")):
            return root  # an item re-exported by the package root (use shop_core::Cents; export * from ...)
        owner = self.symbol_owner.get(rest[-1])
        return [owner] if owner in under else []

    def _package_root(self, package: dict, under: list[str], source_path: str, source_words: set) -> list[str]:
        directory, entry, last = package["dir"], package["entry"], package["segments"][-1] if package["segments"] else ""
        if entry:
            hits = [path for path in under if path == entry or os.path.splitext(path)[0] == os.path.splitext(entry)[0]]
            if hits:
                return hits[:1]
        for sub in ("", "src", "lib", last, f"src/{last}"):
            index_file = self._index_file(posixpath.join(directory, sub).rstrip("/") if sub else directory)
            if index_file and index_file in under:
                return [index_file]
        for sub in ("", "src", "lib"):  # a file named after the package: lib/shop.rb, lib/shop.dart, src/shop.py
            base = posixpath.join(directory, sub, last).strip("/")
            named = [path for path in under if os.path.splitext(path)[0].casefold() == base.casefold()]
            if len(named) == 1:
                return named
        return [path for path in under if self.used_names(path, source_path, source_words)]

    def resolve(self, target: str, source_path: str, source_words: set) -> tuple[list[str], str]:
        """Modules a target names → ``(paths, how)``; ``([], "external")`` when none, ``([], "ambiguous")``.

        Relative targets resolve against the source's directory first. Then, longest first, suffixes of
        the target's segments against module paths (``how="path"``), then against directories
        (``how="package"``: the directory's index file and the modules whose owned names the source
        uses), then the last segment as a name defined in exactly one module (``"symbol"``). A path match
        that drops leading segments of a qualified target (``email.utils`` for ``app/utils.py``) needs
        corroboration: an alias sigil (``@app``, ``$lib``), the module declaring that namespace, or the
        source using the module's names. So does a bare name matching a file outside the source's own
        directory and its ancestors (Go ``"errors"`` against ``internal/store/errors.go``).
        """
        relative = self._resolve_relative(target, source_path, source_words)
        if relative is not None:
            return relative
        parts, ext = self.normalize(target)
        for size in range(len(parts), 0, -1):
            tail = parts[-size:]
            hits = self._suffix_hits(tail, ext, source_path)
            if len(hits) == 1:
                return (hits, "path") if self._corroborated(target, parts, size, hits[0], source_path, source_words) else ([], "external")
            if hits:
                return [], "ambiguous"
            dirs = [d for d in self.by_dir if d and d.split("/")[-size:] == tail]
            if len(dirs) == 1:
                members = [path for path in self.by_dir[dirs[0]] if path != source_path]
                index_file = self._index_file(dirs[0])  # mod http; / import pkg / require('./lib') mean it too
                used = [path for path in members if path == index_file or self.used_names(path, source_path, source_words)]
                if used:
                    return used, "package"
        if parts and parts[-1] in self.symbol_owner and self.symbol_owner[parts[-1]] != source_path:
            return [self.symbol_owner[parts[-1]]], "symbol"
        return [], "external"

    def _corroborated(self, target: str, parts: list[str], size: int, path: str, source_path: str, source_words: set) -> bool:
        if size < len(parts):
            dropped = parts[: len(parts) - size]
            alias = not re.match(r"\w", dropped[0]) and not (self.packages or self.aliases)  # manifests declare the real aliases
            return alias or declares_namespace(self.contents.get(path, ""), dropped[-1]) or bool(self.used_names(path, source_path, source_words))
        if len(parts) == 1 and not _is_relative(target):
            directory, source_dir = posixpath.dirname(path), posixpath.dirname(source_path)
            ancestor = not directory or source_dir == directory or source_dir.startswith(directory + "/")
            return ancestor or bool(self.used_names(path, source_path, source_words))
        return True

    def used_names(self, path: str, source_path: str, source_words: set) -> set:
        """Owning names (``top_symbols``) of *path* that the source uses and does not define itself; a dotted
        name (``MyApp.Accounts.User``) counts when its last part is used."""
        names = self.top_symbols.get(path, set()) - self.all_symbols.get(source_path, set())
        return {name for name in names if name in source_words or name.split(".")[-1] in source_words}

    def namespace_members(self, target: str, source_path: str, source_words: set) -> list[str]:
        """Modules behind a namespace import (``using Acme.Accounting;``) whose namespace is not a path: those
        that declare it (``declares_namespace``) and define a name the source uses."""
        name = target.strip().strip("\"'`<>()[];,").removesuffix(".*").removesuffix("::*")
        if len(re.split(r"::|[./\\]", name)) < 2:
            return []
        return [
            path
            for path in self.paths
            if path != source_path
            and declares_namespace(self.contents.get(path, ""), name)
            and self.used_names(path, source_path, source_words) & self.owned[path]
        ]


def _names_path(evidence: str, name: str, extension: str, extensions: set) -> bool:
    """Whether *name* appears in *evidence* as part of a path or module reference, not as a plain word.

    ``utils.output``, ``./format``, ``"net/socket.h"``, ``crate::store`` and ``socket.h`` qualify;
    ``exclude_patterns=None``, ``config.port`` and ``return config`` do not. An occurrence followed by
    another documented extension (``socket.h`` for ``socket.cpp``) names that other file, not this one.
    """
    for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", evidence):
        before = evidence[match.start() - 1] if match.start() else ""
        after = evidence[match.end() :]
        written = re.match(r"\.\w+", after)
        if written and written.group() in extensions and written.group() != extension:
            continue
        if before in _QUALIFIERS or (extension and after.startswith(extension)) or (after and after[0] in _CLOSERS):
            return True
    return False


def _plain_occurrence(evidence: str, name: str, extension: str, extensions: set) -> bool:
    """Whether *name* occurs in *evidence* other than as another documented file (``socket`` of ``socket.h``
    does not name ``socket.cpp``)."""
    for match in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", evidence):
        written = re.match(r"\.\w+", evidence[match.end() :])
        if not (written and written.group() in extensions and written.group() != extension):
            return True
    return False


def _names_directory(evidence: str, directory: str) -> bool:
    """Whether *evidence* names *directory* by its last two segments (one for a top-level directory) as a
    path or dotted name: ``internal/store`` in ``"example.com/shop/internal/store"``, ``acme.billing`` in
    ``import com.acme.billing.*;``. The stdlib ``"net/http"`` does not name ``internal/http``."""
    tail = [re.escape(part) for part in directory.split("/")[-2:]]
    return re.search(r"(?<!\w)" + r"(?:\.|/|\\|::)".join(tail) + r"(?!\w)", evidence) is not None


def _import_like(evidence: str) -> bool:
    words = _words(evidence.lstrip().lstrip("#@"))
    while words and words[0] in _MODIFIERS:  # pub mod routes; pub(crate) use ...; public import ...
        words = words[1:]
    return bool(words) and words[0] in _IMPORT_WORDS


def evidence_names_module(
    evidence: str, target_path: str, source_path: str, table: ModuleTable, how: str, relative_style: bool = False, per_line: bool = False
) -> bool:
    """The evidence rule: the quoted line must name the resolved module.

    Any of: the module's file stem (for a package: its directory name) as part of a path or module
    reference, or as a word on an import-like line; a name (plain or dotted) only that module defines,
    which the source does not define itself; the module's directory as a path reference with no other
    file of that directory named, when the source uses one of the module's names (Go, Java wildcard
    imports); a dotted namespace the module declares, on an import-like line, when the source uses one
    of the module's names (C# ``using``). Under the relative-import convention a bare quoted specifier
    (``'config'``) never names a local module, nor does the import's own binding. *per_line* (for a
    ``tokens`` match that stitched several lines) makes the import-word clause hold on one line.
    """
    words = set(_words(evidence))
    checked = re.sub(r"[\"'`][\w-]+[\"'`]", " ", evidence) if relative_style else evidence
    name = target_path.split("/")[-2] if how == "package" and "/" in target_path else _stem(target_path)
    extension = "" if how == "package" else os.path.splitext(target_path)[1]
    # Under the relative-import convention the module is always in a quoted specifier: the word clause would
    # accept the local binding of `import config from 'config'`
    lines = split_lines(checked) if per_line else [checked]
    word_clause = not relative_style and any(
        _import_like(line) and _plain_occurrence(_without_bindings(line), name, extension, table.extensions) for line in lines
    )
    if name in set(_words(checked)) and (_names_path(checked, name, extension, table.extensions) or word_clause):
        return True
    own = table.all_symbols.get(source_path, set())
    if any(table.symbol_owner.get(word) == target_path and word not in own for word in words | set(_DOTTED_RE.findall(evidence))):
        return True
    used = table.used_names(target_path, source_path, set(_words(table.contents.get(source_path, ""))))
    if not used:
        return False
    directory = posixpath.dirname(target_path)
    siblings = [path for path in table.by_dir.get(directory, []) if path != target_path]
    names_directory = directory and _names_directory(checked, directory)
    if names_directory and not any(_names_path(checked, _stem(path), os.path.splitext(path)[1], table.extensions) for path in siblings):
        return True
    if _import_like(evidence):
        for dotted in _DOTTED_RE.findall(evidence):
            if declares_namespace(table.contents.get(target_path, ""), dotted):
                return True
    return False


def declares_namespace(content: str, dotted: str) -> bool:
    """Whether *content* has a namespace/package/module declaration line naming *dotted*
    (``namespace Acme.Accounting``, ``package com.acme.billing;``, ``namespace App\\Repo;``)."""
    for line in split_lines(content):
        words = _words(line)
        if words and words[0] in _NAMESPACE_WORDS and dotted in line:
            return True
    return False


def scan_import_candidates(content: str, source_path: str, table: ModuleTable, relative_style: bool = False) -> set[str]:
    """Modules named on import statements of the source (recall diagnostic only; never an edge by itself).

    Comments and block strings are left out (``code_view``) and a line must be an import statement
    (``import_statement_like``) or a path inside a Go ``import ( ... )`` block, so a message such as
    ``"branch is not 'main'"`` never names ``main.py``."""
    found = set()
    lines = code_view(split_lines(_nfc(content)))
    block = import_block_lines(lines)
    for number, line in enumerate(lines):
        if not (import_statement_like(line) or number in block):
            continue
        if relative_style:
            line = re.sub(r"[\"'`][\w-]+[\"'`]", " ", line)
        words = set(_words(line))
        for path in table.paths:
            if path == source_path:
                continue
            stem = _stem(path)
            if stem in words and _names_path(line, stem, os.path.splitext(path)[1], table.extensions):
                found.add(path)
    return found


def relative_import_extensions(located: dict) -> set:
    """File extensions whose files import this project by relative path (``./x``, ``../x``) somewhere.

    Files of such a language write packages as bare names (``import config from 'config'``), so there
    a bare name is external, not a same-named local module, even in a file with no relative import.
    """
    return {os.path.splitext(path)[1] for path, claims in located.items() if any(_is_relative(claim["target"]) for claim in claims)}


def target_written(target: str, evidence: str) -> bool:
    """Whether the claimed target is written in its own evidence line; otherwise it is a paraphrase.

    When a quoted string on the line looks like a module specifier (it has a ``/`` or ``.``, or the
    target's first word — JS/TS, Go, C includes, PHP, Terraform …), the target must be one of the quoted
    strings, whole (``./``, ``/`` and leading dots ignored) or as the end of a path built at run time: so
    ``@acme/api`` is not written in ``'@acme/api/src/client'`` and ``src/lib/money`` not in ``'@lib/money'``.
    Otherwise (Python, Java, Rust, C# …; quoted string literals and Rust lifetimes ignored) the target's
    words must occur in the line in order as whole words — ``app.helpers`` in ``from app import helpers``,
    ``.util`` in ``from . import util`` — but not ``shop::store`` in ``use shop_core::store::Repo``, nor a
    binding introduced by the import (``billing`` of ``from app import models as billing``)."""
    text = _collapse(target.strip().strip("\"'`<>()[];,"))
    if not text:
        return False
    if re.search("[\"'`]", text) and text in _collapse(evidence):  # the whole expression copied: __DIR__ . '/src/Db.php'
        return True
    first = (_words(text) or [""])[0]
    quoted = [q for q in re.findall(r"(?=[\"'`<]([^\"'`<>\s]+)[\"'`>])", evidence) if re.search(r"[/.]", q) or (first and first in _words(q))]
    if quoted:  # whole, or the end of a path built at run time: "$(dirname "$0")/../lib/log.sh", __DIR__ . '/src/Db.php'
        bare = _bare_path(text)
        if any(_bare_path(q) == bare or q.endswith("/" + bare) for q in quoted):
            return True
        # the static part of a path built from a template: require(`./plugins/${name}`) → ./plugins
        if any(_bare_path(q).startswith(bare + "/") and re.search(r"[$#%]\{|\{\w", _bare_path(q)[len(bare) :]) for q in quoted):
            return True
    code = _without_bindings(re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`", " ", evidence))
    if quoted and not _words(code):
        return False
    wanted, have = _words(text), _words(code)
    position = 0
    for word in have:
        if position < len(wanted) and word == wanted[position]:
            position += 1
    return bool(wanted) and position == len(wanted) and not quoted


def _without_bindings(line: str) -> str:
    """The line without the local names an import introduces: ``as billing``, ``=> x``, ``using Env =``,
    ``import Foo = ``. They name the binding, not the imported module."""
    line = re.sub(r"\bas\s+[\w$]+", " ", line)
    line = re.sub(r"=>\s*[\w$]+", " ", line)
    return re.sub(r"^(\s*(?:global\s+)?(?:using|import)\s+)[\w$]+\s*=(?!=)", r"\1", line)


def _bare_path(text: str) -> str:
    return re.sub(r"^(?:\.{1,2}/|/|\.+)+", "", text)


def _imports_target(evidence: str, target: str) -> bool:
    """Whether the evidence imports the target: an import-like line, a Go import-block path line, or the
    target as a whole quoted specifier. A comment, log text or string constant that mentions a declared
    package name does not."""
    lines = split_lines(evidence)
    quoted = re.escape(target.strip().strip("\"'`<>"))
    if any(import_statement_like(line) or _GO_BLOCK_LINE_RE.match(line) for line in lines) or re.search(rf"[\"'`<]{quoted}[\"'`>]", evidence):
        return True
    # An inline qualified use in code (`shop_core::money::total(...)`), not inside a string or comment
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("//", "#", "/*", "*", "--", ";")):
            continue
        code = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`[^`]*`", " ", line)
        if re.search(rf"(?<![\w-]){quoted}(?:::|\.)\w", code):
            return True
    return False


def judge_dependency(
    claim: dict, source_path: str, source_words: set, table: ModuleTable, relative_style: bool, shadowed: frozenset = frozenset()
) -> tuple[str, list]:
    """One located dependency claim → ``("depends_on", [(module, via)])``, ``("external", [])`` or
    ``("rejected", [(module or None, reason)])``.

    *shadowed*: bare names that are the last segment of an external import of the same source
    (``store`` of ``example.com/other/store``): a bare usage ``store.ErrNotFound`` means that package."""
    target, evidence = claim["target"], claim["evidence"]
    if _BARE_NAME_RE.match(target) and normalize_name(target) in shadowed:
        return "external", []
    written = target_written(target, evidence)
    per_line = claim.get("match") == "tokens"
    manifest = table.resolve_manifest(target, source_path, source_words, prefer_local=not relative_style)
    if manifest is not None:  # declared names win over the relative-import convention: `import 'utils'` may be a workspace package
        targets, _prefix = manifest
        if not targets:
            return "external", []
        if written and _imports_target(evidence, target):
            return "depends_on", [(module, "manifest") for module in targets]
        return "rejected", [(module, "evidence does not import the declared package or alias") for module in targets]
    if relative_style and _BARE_NAME_RE.match(claim["target"]):
        return "external", []
    targets, how = table.resolve(claim["target"], source_path, source_words)
    if not targets and how == "external" and _import_like(claim["evidence"]):
        targets, how = table.namespace_members(claim["target"], source_path, source_words), "namespace"
        if targets:
            return "depends_on", [(target, how) for target in targets]
    if not targets:
        return ("rejected", [(None, "target matches several modules")]) if how == "ambiguous" else ("external", [])
    if not written:
        # A paraphrased target. Still fine when the model named the file instead of the specifier (the target is
        # the module's path and the line passes the evidence rule for it), or the line uses a name only that
        # module defines
        own = table.all_symbols.get(source_path, set())
        words = set(_words(evidence)) | set(_DOTTED_RE.findall(evidence))
        path_target = target.strip().replace("\\", "/")
        kept = [
            (module, how)
            for module in targets
            if any(table.symbol_owner.get(word) == module and word not in own for word in words)
            or (module.endswith(path_target) and evidence_names_module(evidence, module, source_path, table, how, relative_style, per_line))
        ]
        return ("depends_on", kept) if kept else ("rejected", [(module, "target is not written in the evidence") for module in targets])
    kept = [(module, how) for module in targets if evidence_names_module(evidence, module, source_path, table, how, relative_style, per_line)]
    if kept:
        return "depends_on", kept
    return "rejected", [(module, "evidence does not name the module") for module in targets]


def shadowed_names(claims: list[dict], verdicts: list[tuple]) -> frozenset:
    """Bare names that are the last segment of an external import and of no internal import of the same
    source (``store`` of ``example.com/other/store``): a bare ``store.X`` there means that external package."""

    def last(claim):
        segments = _name_segments(claim["target"])
        return segments[-1] if len(segments) > 1 else None

    external = {last(claim) for claim, (verdict, _) in zip(claims, verdicts, strict=True) if verdict == "external"} - {None}
    internal = {last(claim) for claim, (verdict, _) in zip(claims, verdicts, strict=True) if verdict == "depends_on"} - {None}
    return frozenset(external - internal)


def verify_dependencies(located: dict, contents: dict, table: ModuleTable) -> dict:
    """Resolve each module's located dependency claims → ``{path: {"depends_on", "external", "rejected", "missed"}}``.

    ``depends_on`` entries are ``{"module", "target", "line", "evidence", "via"}`` that pass the
    evidence rule (``target`` as written in the source); ``missed`` lists modules an import-like line
    names but no claim covered (a recall hint).
    """
    results = {}
    relative_extensions = relative_import_extensions(located)
    for path, claims in located.items():
        words = set(_words(contents.get(path, "")))
        depends_on, external, rejected, seen = [], [], [], set()
        relative_style = os.path.splitext(path)[1] in relative_extensions
        verdicts = [judge_dependency(claim, path, words, table, relative_style) for claim in claims]
        shadowed = shadowed_names(claims, verdicts)
        if shadowed:
            verdicts = [judge_dependency(claim, path, words, table, relative_style, shadowed) for claim in claims]
        for claim, (verdict, detail) in zip(claims, verdicts, strict=True):
            if verdict == "external":
                external.append({"name": claim["target"], "line": claim["line"]})
            elif verdict == "rejected":
                rejected.extend(
                    {"kind": "dependency", **claim, **({"module": module} if module else {}), "reason": reason} for module, reason in detail
                )
            else:
                for module, how in detail:
                    if module not in seen:
                        seen.add(module)
                        depends_on.append(
                            {"module": module, "target": claim["target"], "line": claim["line"], "evidence": claim["evidence"], "via": how}
                        )
        missed = sorted(scan_import_candidates(contents.get(path, ""), path, table, relative_style) - seen)
        results[path] = {"depends_on": depends_on, "external": external, "rejected": rejected, "missed": missed}
    return results


# ---------------------------------------------------------------------------
# facts.json
# ---------------------------------------------------------------------------


def facts_hash(signature: str, path: str, content: str) -> str:
    return hashlib.md5(f"{signature}|{path}|{content}".encode()).hexdigest()


def source_commit(local_dir) -> str | None:
    """HEAD commit of the crawled checkout (not of this tool's working directory), or None."""
    if not local_dir or not os.path.isdir(local_dir):
        return None
    try:
        out = subprocess.run(["git", "-C", local_dir, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def build_facts_document(project_name: str, commit, modules: dict, manifests: dict | None = None) -> dict:
    """The published document: every listed fact is backed by a source line; lists may be incomplete.
    ``manifests``: the names and aliases the project's code is imported by, per manifest file."""
    return {
        "schema": FACTS_SCHEMA,
        "project": project_name,
        "commit": commit,
        "note": (
            "Every symbol, dependency, config key and error below was found in the source at the given line. "
            "Presence is verified, completeness is not: 'coverage' compares verified to claimed facts per module."
        ),
        "modules": modules,
        "manifests": manifests or {},
    }


def load_facts(path: str, section: str = "modules") -> dict:
    """``{path: entry}`` of a section (``modules`` or ``manifests``) of an earlier facts.json, or ``{}``."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError):
        return {}
    entries = document.get(section) if isinstance(document, dict) else None
    return entries if isinstance(entries, dict) and document.get("schema") == FACTS_SCHEMA else {}


def save_facts(path: str, document: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=1, ensure_ascii=False)
    os.replace(tmp_path, path)


def facts_path(output_dir: str, project_name: str, is_mkdocs: bool) -> str:
    """docs/api/facts.json under --mkdocs (published with the site and kept by CI's docs cache), else next to the pages."""
    base = os.path.join(output_dir, project_name)
    return os.path.join(base, "docs", "api", FACTS_FILENAME) if is_mkdocs else os.path.join(base, FACTS_FILENAME)
