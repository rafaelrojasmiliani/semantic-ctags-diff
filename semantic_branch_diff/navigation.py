"""Vim / Flog navigation helpers.

Centralizes symbol picking, flog ``-limit=`` strings, and cursor-at-symbol
resolution so Vim only handles buffers and editor integration — not ctags parsing
or symbol priority heuristics (those live in :mod:`semantic_branch_diff.symbols`).
"""

from __future__ import annotations

import re
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
    """Build a vim-flog ``-limit=`` value: ``start,end:repo-relative-path``.

    Args:
        path: Repo-relative file path.
        start_line: 1-based start line (inclusive).
        end_line: 1-based end line (inclusive).

    Returns:
        Limit string understood by vim-flog.
    """
    return f"{start_line},{end_line}:{path}"


def symbol_label(kind: str, qualified_name: str) -> str:
    """Human-readable symbol label for pickers and echo messages."""
    name = qualified_name or "[anonymous]"
    return f"{kind} {name}"


def kind_matches_filter(kind: str, kind_filter: str) -> bool:
    """Return whether ``kind`` matches a Vim-style Flog kind filter.

    Filters mirror the historical ``files`` script:
    ``symbol`` (or empty) matches all; ``function``, ``class``, ``namespace``
    match their respective families.

    Args:
        kind: Normalized symbol kind.
        kind_filter: Filter name from Vim (case-insensitive).

    Returns:
        ``True`` when the symbol should be included.
    """
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
    """Pick the best enclosing symbol at ``line``, optionally filtered by kind.

    Args:
        symbols: Parsed symbols for one file revision.
        line: 1-based line number.
        kind_filter: Optional kind filter (see :func:`kind_matches_filter`).

    Returns:
        Best matching symbol or ``None``.
    """
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


def symbol_to_navigation_entry(
    *,
    path: str,
    kind: str,
    qualified_name: str,
    name: str,
    start_line: int,
    end_line: int,
    classification: str,
) -> dict[str, Any]:
    """Build one navigation record for JSON output and Vim pickers."""
    return {
        "path": path,
        "kind": kind,
        "qualified_name": qualified_name,
        "name": name,
        "line": start_line,
        "range": [start_line, end_line],
        "classification": classification,
        "label": f"{path}: {symbol_label(kind, qualified_name)}",
        "flog_limit": flog_line_limit(path, start_line, end_line),
    }


def enrich_symbol_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Add ``label`` and ``flog_limit`` to a symbol summary dict in-place copy."""
    out = dict(record)
    path = str(out.get("file", out.get("path", "")))
    if "new_range" in out and len(out["new_range"]) >= 2:
        start, end = int(out["new_range"][0]), int(out["new_range"][1])
    elif "range" in out and len(out["range"]) >= 2:
        start, end = int(out["range"][0]), int(out["range"][1])
    else:
        start = int(out.get("line", 1))
        end = start
    kind = str(out.get("kind", "symbol"))
    qn = str(out.get("qualified_name", out.get("name", "")))
    out["path"] = path
    out["line"] = start
    out["label"] = f"{path}: {symbol_label(kind, qn)}"
    out["flog_limit"] = flog_line_limit(path, start, end)
    return out


def collect_navigation_choices(
    result: SemanticDiffResult,
    *,
    include_modified: bool = True,
    include_added: bool = False,
    include_removed: bool = False,
) -> list[dict[str, Any]]:
    """Flatten branch-diff symbols into Vim/Flog picker entries.

    Args:
        result: Completed semantic diff.
        include_modified: Include modified symbols (default for branch review).
        include_added: Include added symbols.
        include_removed: Include removed symbols.

    Returns:
        List of navigation dicts with ``label`` and ``flog_limit``.
    """
    choices: list[dict[str, Any]] = []
    for file_result in result.files:
        path = file_result.path
        if include_modified:
            for sym in file_result.modified_symbols:
                choices.append(
                    symbol_to_navigation_entry(
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
                    symbol_to_navigation_entry(
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
                    symbol_to_navigation_entry(
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
    """Resolve the symbol at ``line`` in source text (buffer / staged file).

    Used by Vim ``Flogsplit*`` commands via the ``symbol-at`` CLI mode instead
    of re-implementing ctags in Vimscript.

    Args:
        source_content: Full file text.
        source_path: Path used for extension and flog limit (repo-relative).
        line: 1-based cursor line.
        ctags_executable: Ctags binary path.
        kind_filter: Optional kind filter.

    Returns:
        JSON-serializable dict with ``symbol`` (or ``null``), ``flog_limit``,
        ``label``, ``file``, and ``line``.
    """
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
    entry = symbol_to_navigation_entry(
        path=source_path,
        kind=sym.kind,
        qualified_name=sym.qualified_name,
        name=sym.name,
        start_line=sym.start_line,
        end_line=sym.end_line,
        classification="current",
    )
    base["symbol"] = {
        "kind": sym.kind,
        "qualified_name": sym.qualified_name,
        "name": sym.name,
        "range": [sym.start_line, sym.end_line],
    }
    base["label"] = entry["label"].split(": ", 1)[-1]
    base["flog_limit"] = entry["flog_limit"]
    return base


def symbol_at_path(
    file_path: Path,
    line: int,
    *,
    ctags_executable: str = "ctags",
    kind_filter: str = "",
    repo_relative_path: str | None = None,
) -> dict[str, Any]:
    """Resolve symbol at ``line`` by reading ``file_path`` from disk.

    Args:
        file_path: Absolute or relative path to source file.
        line: 1-based line number.
        ctags_executable: Ctags binary.
        kind_filter: Optional kind filter.
        repo_relative_path: Path stored in flog limit (defaults to ``file_path`` name).

    Returns:
        Same structure as :func:`symbol_at_source`.
    """
    content = file_path.read_text(encoding="utf-8", errors="replace")
    display_path = repo_relative_path if repo_relative_path is not None else file_path.as_posix()
    return symbol_at_source(
        source_content=content,
        source_path=display_path,
        line=line,
        ctags_executable=ctags_executable,
        kind_filter=kind_filter,
    )
