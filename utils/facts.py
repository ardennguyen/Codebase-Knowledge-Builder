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
}
_MODIFIERS = {"pub", "crate", "public", "private", "protected", "internal", "static"}
_CONTAINER_KINDS = {"class", "struct", "interface", "enum", "trait", "type", "module", "namespace", "impl", "object", "record", "protocol"}
_OWNER_EXCLUDED_KINDS = {"method"}  # called on objects of any type: proves nothing about which file a line uses
_NAMESPACE_WORDS = {"namespace", "package", "module", "defmodule", "library", "unit"}  # declaration lines
_INDEX_STEMS = ("mod", "index", "__init__", "init", "main")  # the file a directory import means, in this preference
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
        """The matched source text, at most ``_EXCERPT`` characters around the quote: ``(text, truncated)``."""
        text = self.text(first, last).strip()
        if len(text) <= _EXCERPT:
            return text, False
        flat, wanted = _collapse(text), _collapse(quote)
        pos = max(flat.find(wanted), 0)
        start = max(0, min(pos - (_EXCERPT - len(wanted)) // 2, len(flat) - _EXCERPT))
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
    and 1-based ``line``; ``rejected`` lists the others with a reason. Reply items the parser could not
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
        entry = {"target": target, "line": first + 1, "evidence": text, "match": how}
        result["dependencies"].append({**entry, "truncated": True} if truncated else entry)

    for key in ("config", "errors"):
        for item in _claim_list(claims, key):
            claimed += 1
            name, evidence = _as_text(item.get("name")).strip(), _as_text(item.get("evidence"))
            matches = [m for m in (index.locate(evidence) if name else []) if _names_in(index.text(m[0], m[1]), name)]
            if not matches:
                rejected.append({"kind": key, "name": name, "evidence": evidence, "reason": "name/evidence not in source"})
                continue
            first, last, how = matches[0]
            text, truncated = index.excerpt(first, last, evidence)
            entry = {"name": name, "line": first + 1, "evidence": text, "match": how}
            if key == "config":
                entry["kind"] = _as_text(item.get("kind")).strip() or "config"
            result[key].append({**entry, "truncated": True} if truncated else entry)

    result["rejected"] = rejected
    result["claimed"] = claimed
    result["found"] = claimed - len(rejected)
    return result


def _verify_symbols(symbols: list[dict], index: SourceIndex) -> tuple[list, list]:
    """Locate each symbol's signature, members inside their parent.

    Parents are placed before their members. A member is searched from its parent's line to the next
    top-level symbol, so ``prep`` declared in ten classes of one file lands on the right line; failing
    that, file-wide, where a match counts only when its text names the parent (a Go receiver, a C++
    ``Class::``) or the nearest class-like symbol declared above it is that parent (or there is none).
    A member signature matching several lines that no parent span tells apart is rejected; a
    top-level one (conditional definitions) is kept at its first line with ``ambiguous_lines``.
    """
    kept, rejected, placed = [], [], {}
    pending, unscoped = list(symbols), False
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
                matches = [m for m in index.locate(signature, start, end) if name and _names_in(index.text(m[0], m[1]), name)]
                scoped = bool(matches)
            if not matches:
                matches = [m for m in index.locate(signature) if name and _names_in(index.text(m[0], m[1]), name)]
                if parent:
                    matches = [m for m in matches if parent in _words(index.text(m[0], m[1])) or _enclosing(containers, m[0]) in (None, parent)]
            if not matches or (len(matches) > 1 and parent and not scoped):
                if not matches:
                    reason = "signature not in source" if not index.locate(signature) else "name not in its signature, or outside its parent"
                else:
                    reason = "signature matches several lines; the parent does not tell them apart"
                rejected.append({"kind": "symbol", "name": name, "parent": parent, "signature": signature, "reason": reason})
                continue
            first, last, how = matches[0]
            text, truncated = index.excerpt(first, last, signature)
            entry = {
                "name": name,
                "kind": _as_text(item.get("kind")).strip() or "symbol",
                "parent": parent,
                "visibility": _as_text(item.get("visibility")).strip() or None,
                "line": first + 1,
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


def _enclosing(containers: list[tuple[int, str]], line: int) -> str | None:
    """Name of the nearest class/struct/module-like symbol declared before *line*, if any."""
    names = [name for start, name in containers if start < line]
    return names[-1] if names else None


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

    def __init__(self, paths: list[str], symbols_by_path: dict, contents: dict | None = None):
        """*symbols_by_path*: ``{path: [{"name", "kind", ...}, ...]}`` (verified symbols). Every symbol but a
        method owns its module (classes, functions, constants, also inside a module or namespace): a
        method name like ``get`` or ``to_h`` is called on objects of many types and proves nothing about
        which file a line uses."""
        self.paths = list(paths)
        self.contents = contents or {}
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
        dots = re.match(r"^(\.+)(\w[\w.]*)$", text)
        if dots:
            text = "../" * (len(dots.group(1)) - 1) + "./" + dots.group(2).replace(".", "/")
        if not text.startswith(("./", "../")):
            return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), text))
        stem_match = [path for path in self.paths if path != source_path and (os.path.splitext(path)[0] == base or path == base)]
        if not stem_match:  # './types' → types.d.ts: every extension dropped
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
        if dots and not stem_match:
            return [], "external"  # a leading-dot module path is always file-relative
        return None

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
            alias = not re.match(r"\w", dropped[0])
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
    word_clause = not relative_style and any(_import_like(line) and _plain_occurrence(line, name, extension, table.extensions) for line in lines)
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
    """Modules named on import-like lines of the source (recall diagnostic only; never an edge by itself)."""
    found = set()
    for line in split_lines(content):
        if not (_import_like(line) or _GO_BLOCK_LINE_RE.match(line)):
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


def judge_dependency(claim: dict, source_path: str, source_words: set, table: ModuleTable, relative_style: bool) -> tuple[str, list]:
    """One located dependency claim → ``("depends_on", [(module, via)])``, ``("external", [])`` or
    ``("rejected", [(module or None, reason)])``."""
    if relative_style and _BARE_NAME_RE.match(claim["target"]):
        return "external", []
    targets, how = table.resolve(claim["target"], source_path, source_words)
    if not targets and how == "external" and _import_like(claim["evidence"]):
        targets, how = table.namespace_members(claim["target"], source_path, source_words), "namespace"
        if targets:
            return "depends_on", [(target, how) for target in targets]
    if not targets:
        return ("rejected", [(None, "target matches several modules")]) if how == "ambiguous" else ("external", [])
    per_line = claim.get("match") == "tokens"
    kept = [
        (target, how) for target in targets if evidence_names_module(claim["evidence"], target, source_path, table, how, relative_style, per_line)
    ]
    if kept:
        return "depends_on", kept
    return "rejected", [(target, "evidence does not name the module") for target in targets]


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
        for claim in claims:
            verdict, detail = judge_dependency(claim, path, words, table, relative_style)
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


def build_facts_document(project_name: str, commit, modules: dict) -> dict:
    """The published document: every listed fact is backed by a source line; lists may be incomplete."""
    return {
        "schema": FACTS_SCHEMA,
        "project": project_name,
        "commit": commit,
        "note": (
            "Every symbol, dependency, config key and error below was found in the source at the given line. "
            "Presence is verified, completeness is not: 'coverage' compares verified to claimed facts per module."
        ),
        "modules": modules,
    }


def load_facts(path: str) -> dict:
    """``{module path: entry}`` of an earlier facts.json, or ``{}``."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError):
        return {}
    modules = document.get("modules") if isinstance(document, dict) else None
    return modules if isinstance(modules, dict) and document.get("schema") == FACTS_SCHEMA else {}


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
