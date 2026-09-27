"""Vim / Flog navigation helpers.

Centralizes symbol picking, flog ``-limit=`` strings, and cursor-at-symbol
resolution. Domain type is :class:`NavigationEntry`; it holds a ctags
:class:`~ctags3_improved.model.Symbol` plus a classification.
``to_dict()`` is only for the JSON / Vim wire boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ctags3_improved import Symbol, SymbolKey

from semantic_branch_diff.ctags_adapter import generate_symbols
from semantic_branch_diff.diff_engine import SemanticDiffResult
from semantic_branch_diff.symbols import (
    CLASS_KINDS,
    FUNCTION_KINDS,
    best_enclosing_symbol,
    kind_priority,
)

_NAMESPACE_KINDS = frozenset({"namespace", "module", "package"})


def flog_line_limit(path: str, start_line: int, end_line: int) -> str:
    """Build a vim-flog ``-limit=`` value: ``start,end:repo-relative-path``."""
    return f"{start_line},{end_line}:{path}"


def symbol_label(kind: str, qualified_name: str) -> str:
    """Human-readable symbol label for pickers and echo messages."""
    name = qualified_name or "[anonymous]"
    return f"{kind} {name}"


def _symbol_from_wire_dict(record: dict[str, Any]) -> Symbol:
    """Rebuild a minimal :class:`Symbol` from a JSON symbol summary dict."""
    path = str(record.get("file", record.get("path", "")))
    if "new_range" in record and len(record["new_range"]) >= 2:
        start, end = int(record["new_range"][0]), int(record["new_range"][1])
    elif "range" in record and len(record["range"]) >= 2:
        start, end = int(record["range"][0]), int(record["range"][1])
    else:
        start = int(record.get("line", 1))
        end = start
    kind = str(record.get("kind", "symbol"))
    qn = str(record.get("qualified_name", record.get("name", "")))
    name = str(record.get("name", qn.split("::")[-1] if qn else ""))
    return Symbol(
        key=SymbolKey(kind=kind, qualified_name=qn),
        name=name,
        qualified_name=qn,
        kind=kind,
        raw_kind=kind,
        scope=str(record.get("scope", "")),
        path=path,
        start_line=start,
        end_line=end,
    )


@dataclass(frozen=True)
class NavigationEntry:
    """One picker / Flog navigation target (typed until JSON serialization)."""

    symbol: Symbol
    classification: str

    @classmethod
    def from_symbol(cls, sym: Symbol, *, classification: str) -> NavigationEntry:
        """Build an entry from a ctags :class:`Symbol`."""
        return cls(symbol=sym, classification=classification)

    @property
    def label(self) -> str:
        """Path-prefixed label for branch-diff pickers."""
        s = self.symbol
        return f"{s.path}: {symbol_label(s.kind, s.qualified_name)}"

    @property
    def short_label(self) -> str:
        """Kind + name only (symbol-at cursor)."""
        s = self.symbol
        return symbol_label(s.kind, s.qualified_name)

    @property
    def flog_limit(self) -> str:
        s = self.symbol
        return flog_line_limit(s.path, s.start_line, s.end_line)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / Vim. Call only at the wire boundary."""
        s = self.symbol
        return {
            "path": s.path,
            "kind": s.kind,
            "qualified_name": s.qualified_name,
            "name": s.name,
            "line": s.start_line,
            "range": [s.start_line, s.end_line],
            "classification": self.classification,
            "label": self.label,
            "flog_limit": self.flog_limit,
        }


def kind_matches_filter(kind: str, kind_filter: str) -> bool:
    """Return whether ``kind`` matches a Vim-style Flog kind filter."""
    filt = (kind_filter or "symbol").strip().lower()
    k = kind.lower()
    if filt in {"", "symbol"}:
        return True
    if filt == "function":
        return k in FUNCTION_KINDS or k in {"procedure", "subroutine"}
    if filt == "class":
        return k in CLASS_KINDS or k == "enum"
    if filt == "namespace":
        return k in _NAMESPACE_KINDS
    return bool(re.search(re.escape(filt), k))


def best_symbol_for_line(
    symbols: list[Symbol],
    line: int,
    *,
    kind_filter: str = "",
) -> Symbol | None:
    """Pick the best enclosing symbol at ``line``, optionally filtered by kind."""
    candidates = [
        s
        for s in symbols
        if s.contains_line(line) and not s.file_scope and kind_matches_filter(s.kind, kind_filter)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: (kind_priority(s.kind), s.range_size(), s.start_line),
    )


def symbol_to_navigation_entry(sym: Symbol, *, classification: str) -> NavigationEntry:
    """Build a :class:`NavigationEntry` from a :class:`Symbol`."""
    return NavigationEntry.from_symbol(sym, classification=classification)


def enrich_symbol_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Attach ``label`` / ``flog_limit`` to a symbol summary dict at JSON time."""
    out = dict(record)
    entry = NavigationEntry.from_symbol(
        _symbol_from_wire_dict(out),
        classification=str(out.get("classification", "")),
    )
    out["path"] = entry.symbol.path
    out["line"] = entry.symbol.start_line
    out["label"] = entry.label
    out["flog_limit"] = entry.flog_limit
    return out


def collect_navigation_choices(
    result: SemanticDiffResult,
    *,
    include_modified: bool = True,
    include_added: bool = False,
    include_removed: bool = False,
) -> list[NavigationEntry]:
    """Flatten branch-diff symbols into typed navigation entries."""
    choices: list[NavigationEntry] = []
    for file_result in result.files:
        if include_modified:
            for change in file_result.modified_symbols:
                choices.append(
                    NavigationEntry.from_symbol(change.new, classification="modified")
                )
        if include_added:
            for sym in file_result.added_symbols:
                choices.append(NavigationEntry.from_symbol(sym, classification="added"))
        if include_removed:
            for sym in file_result.removed_symbols:
                choices.append(NavigationEntry.from_symbol(sym, classification="removed"))
    return choices


def symbol_at_source(
    *,
    source_content: str,
    source_path: str,
    line: int,
    ctags_executable: str = "ctags",
    kind_filter: str = "",
) -> dict[str, Any]:
    """Resolve the symbol at ``line``; returns a JSON-ready dict for the CLI."""
    symbols = generate_symbols(
        source_content=source_content,
        source_path=source_path,
        ctags_executable=ctags_executable,
    )
    sym = best_symbol_for_line(symbols, line, kind_filter=kind_filter)
    base: dict[str, Any] = {
        "file": source_path,
        "line": line,
        "kind_filter": kind_filter or "symbol",
        "symbol": None,
        "label": "",
        "flog_limit": "",
    }
    if sym is None:
        return base
    entry = NavigationEntry.from_symbol(sym, classification="current")
    base["symbol"] = {
        "kind": sym.kind,
        "qualified_name": sym.qualified_name,
        "name": sym.name,
        "range": [sym.start_line, sym.end_line],
    }
    base["label"] = entry.short_label
    base["flog_limit"] = entry.flog_limit
    return base


def symbol_at_path(
    file_path: Path,
    line: int,
    *,
    ctags_executable: str = "ctags",
    kind_filter: str = "",
    repo_relative_path: str | None = None,
) -> dict[str, Any]:
    """Resolve symbol at ``line`` by reading ``file_path`` from disk."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    display_path = repo_relative_path if repo_relative_path is not None else file_path.as_posix()
    return symbol_at_source(
        source_content=content,
        source_path=display_path,
        line=line,
        ctags_executable=ctags_executable,
        kind_filter=kind_filter,
    )


__all__ = [
    "NavigationEntry",
    "best_enclosing_symbol",
    "best_symbol_for_line",
    "collect_navigation_choices",
    "enrich_symbol_dict",
    "flog_line_limit",
    "kind_matches_filter",
    "symbol_at_path",
    "symbol_at_source",
    "symbol_label",
    "symbol_to_navigation_entry",
]
