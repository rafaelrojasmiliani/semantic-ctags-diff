"""JSON and Markdown renderers.

Convert :class:`~semantic_branch_diff.diff_engine.SemanticDiffResult` into
stable, human-readable output for the CLI and Vim integration.
"""

from __future__ import annotations

import json
from typing import Any

from semantic_branch_diff.diff_engine import SemanticDiffResult
from semantic_branch_diff.symbols import is_reportable

# Only "class" pluralizes irregularly; everything else takes a plain "s".
_KIND_LABELS = {"class": "Classes"}


def render_json(result: SemanticDiffResult, indent: int = 2) -> str:
    """Serialize a semantic diff result to sorted, indented JSON.

    Used as the default CLI format. ``sort_keys=True`` keeps output stable
    across runs for scripting and tests.

    Args:
        result: Completed diff from :func:`semantic_diff`.
        indent: JSON indentation width (default 2).

    Returns:
        JSON string with trailing newline.
    """
    return json.dumps(result.to_dict(), indent=indent, sort_keys=True) + "\n"


def _format_lines(lines: list[int]) -> str:
    """Format a list of line numbers as comma-separated text for Markdown.

    Args:
        lines: 1-based line numbers.

    Returns:
        String like ``"12, 13, 17"``.
    """
    return ", ".join(str(ln) for ln in lines)


def _kind_label(kind: str) -> str:
    """Return the plural section heading for a symbol kind.

    Args:
        kind: Normalized kind such as ``function`` or ``class``.

    Returns:
        Heading text like ``Functions`` or ``Classes``.
    """
    return _KIND_LABELS.get(kind, kind.capitalize() + "s")


def _clean(entries: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Drop unreportable symbols and collapse repeats of the same symbol.

    A namespace reopened in twenty files yields twenty identical tags; the
    report only needs to say it changed once. Locals, free variables, and
    anonymous-namespace symbols are dropped entirely (see
    :func:`~semantic_branch_diff.symbols.is_reportable`).

    Args:
        entries: ``(path, symbol)`` pairs flattened across files.

    Returns:
        Filtered list, first occurrence of each ``(kind, qualified_name)`` kept.
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, Any]] = []
    for path, sym in entries:
        if not is_reportable(sym.kind, sym.qualified_name):
            continue
        token = (sym.kind, sym.qualified_name)
        if token in seen:
            continue
        seen.add(token)
        out.append((path, sym))
    return out


def _by_kind_section(entries: list[tuple[str, Any]], marker: str) -> list[str]:
    """Render symbols grouped under one heading per kind.

    Args:
        entries: Cleaned ``(path, symbol)`` pairs.
        marker: Bullet prefix (``+`` added, ``-`` removed).

    Returns:
        Markdown lines. Names only — the Vim report resolves file and line from
        the JSON result, so ranges do not need to be printed.
    """
    by_kind: dict[str, list[Any]] = {}
    for _path, sym in entries:
        by_kind.setdefault(sym.kind, []).append(sym)

    lines: list[str] = []
    for kind in sorted(by_kind):
        lines.append(_kind_label(kind) + ":")
        for sym in by_kind[kind]:
            lines.append(f"  {marker} {sym.qualified_name}")
        lines.append("")
    return lines


def render_markdown(result: SemanticDiffResult) -> str:
    """Render a semantic diff as human-readable Markdown.

    Produces sections for added, removed, and modified symbols plus file-scope
    line changes. Intended for terminal display and ``:read !`` in Vim.

    Args:
        result: Completed diff from :func:`semantic_diff`.

    Returns:
        Multi-line Markdown document (no trailing requirement).
    """
    lines: list[str] = []
    # Title block mirrors the acceptance-criteria example format.
    lines.append(f"Semantic branch diff: {result.base_ref}...{result.head_ref}")
    lines.append("=" * (len(lines[0]) - 1))
    lines.append("")

    # Flatten per-file symbol lists into global sections grouped by change type.
    added = _clean([(f.path, s) for f in result.files for s in f.added_symbols])
    removed = _clean([(f.path, s) for f in result.files for s in f.removed_symbols])
    modified = [(f.path, s) for f in result.files for s in f.modified_symbols]
    file_scope = [
        (f.path, f.file_scope_changes) for f in result.files if f.file_scope_changes.added_lines or f.file_scope_changes.deleted_lines
    ]

    if added:
        lines.append("Added symbols")
        lines.append("=============")
        lines.append("")
        lines.extend(_by_kind_section(added, "+"))

    if removed:
        lines.append("Removed symbols")
        lines.append("===============")
        lines.append("")
        lines.extend(_by_kind_section(removed, "-"))

    if modified:
        lines.append("Modified symbols")
        lines.append("----------------")
        lines.append("")
        # Grouped by file rather than by kind: the same namespace is typically
        # modified in many files, and the path keeps each entry jumpable.
        by_file: dict[str, list[Any]] = {}
        for path, sym in modified:
            by_file.setdefault(path, []).append(sym)
        for path in sorted(by_file):
            entries = _clean([(path, sym) for sym in by_file[path]])
            if not entries:
                continue
            lines.append(path)
            lines.append("")
            for _path, sym in entries:
                lines.append(f"  ~ {sym.kind} {sym.qualified_name}")
            lines.append("")

    if file_scope:
        lines.append("File-scope changes")
        lines.append("------------------")
        lines.append("")
        for path, changes in file_scope:
            lines.append(path)
            lines.append("")
            if changes.added_lines:
                lines.append(f"* added lines: {_format_lines(changes.added_lines)}")
            if changes.deleted_lines:
                lines.append(f"* deleted lines: {_format_lines(changes.deleted_lines)}")
            lines.append("")

    if not added and not removed and not modified and not file_scope:
        lines.append("No semantic changes detected in analyzed files.")
        lines.append("")

    return "\n".join(lines)
