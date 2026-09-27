"""Vim / Flog navigation helpers.

Centralizes symbol picking, flog ``-limit=`` strings, and cursor-at-symbol
resolution. Domain type is :class:`NavigationEntry`; ``to_dict()`` is only for
the JSON / Vim wire boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_branch_diff.ctags_adapter import generate_symbols
from semantic_branch_diff.diff_engine import SemanticDiffResult
from semantic_branch_diff.symbols import (
    CLASS_KINDS,
    FUNCTION_KINDS,
    Symbol,
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


@dataclass(frozen=True)
class NavigationEntry:
    """One picker / Flog navigation target (typed until JSON serialization)."""

    path: str
    kind: str
    qualified_name: str
    name: str
    start_line: int
    end_line: int
    classification: str

    @classmethod
    def from_symbol(cls, sym: Symbol, *, classification: str) -> NavigationEntry:
        """Build an entry from a ctags :class:`Symbol`."""
        return cls(
            path=sym.path,
            kind=sym.kind,
            qualified_name=sym.qualified_name,
            name=sym.name,
            start_line=sym.start_line,
            end_line=sym.end_line,
            classification=classification,
        )

    @classmethod
    def from_range(
        cls,
        *,
        path: str,
        kind: str,
        qualified_name: str,
        name: str,
        start_line: int,
        end_line: int,
        classification: str,
    ) -> NavigationEntry:
        """Build an entry from a diff summary (added/removed/modified)."""
        return cls(
            path=path,
            kind=kind,
            qualified_name=qualified_name,
            name=name,
            start_line=start_line,
            end_line=end_line,
            classification=classification,
        )

    @property
    def label(self) -> str:
        """Path-prefixed label for branch-diff pickers."""
        return f"{self.path}: {symbol_label(self.kind, self.qualified_name)}"

    @property
    def short_label(self) -> str:
        """Kind + name only (symbol-at cursor)."""
        return symbol_label(self.kind, self.qualified_name)

    @property
    def flog_limit(self) -> str:
        return flog_line_limit(self.path, self.start_line, self.end_line)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON / Vim. Call only at the wire boundary."""
        return {
            "path": self.path,
            "kind": self.kind,
            "qualified_name": self.qualified_name,
            "name": self.name,
            "line": self.start_line,
            "range": [self.start_line, self.end_line],
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
    path = str(out.get("file", out.get("path", "")))
    if "new_range" in out and len(out["new_range"]) >= 2:
        start, end = int(out["new_range"][0]), int(out["new_range"][1])
    elif "range" in out and len(out["range"]) >= 2:
        start, end = int(out["range"][0]), int(out["range"][1])
    else:
        start = int(out.get("line", 1))
        end = start
    entry = NavigationEntry.from_range(
        path=path,
        kind=str(out.get("kind", "symbol")),
        qualified_name=str(out.get("qualified_name", out.get("name", ""))),
        name=str(out.get("name", "")),
        start_line=start,
        end_line=end,
        classification=str(out.get("classification", "")),
    )
    out["path"] = entry.path
    out["line"] = entry.start_line
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
        path = file_result.path
        if include_modified:
            for sym in file_result.modified_symbols:
                choices.append(
                    NavigationEntry.from_range(
                        path=path,
                        kind=sym.kind,
                        qualified_name=sym.qualified_name,
                        name=sym.name,
                        start_line=sym.new_range[0],
                        end_line=sym.new_range[1],
                        classification="modified",
                    )
                )
        if include_added:
            for sym in file_result.added_symbols:
                choices.append(
                    NavigationEntry.from_range(
                        path=path,
                        kind=sym.kind,
                        qualified_name=sym.qualified_name,
                        name=sym.name,
                        start_line=sym.range[0],
                        end_line=sym.range[1],
                        classification="added",
                    )
                )
        if include_removed:
            for sym in file_result.removed_symbols:
                choices.append(
                    NavigationEntry.from_range(
                        path=path,
                        kind=sym.kind,
                        qualified_name=sym.qualified_name,
                        name=sym.name,
                        start_line=sym.range[0],
                        end_line=sym.range[1],
                        classification="removed",
                    )
                )
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
