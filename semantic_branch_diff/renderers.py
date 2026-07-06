"""JSON and Markdown renderers.

Convert :class:`~semantic_branch_diff.diff_engine.SemanticDiffResult` into
stable, human-readable output for the CLI and Vim integration.
"""

from __future__ import annotations

import json
from typing import Any

from semantic_branch_diff.diff_engine import SemanticDiffResult


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


def _format_range(rng: list[int]) -> str:
    """Format a two-element line range for Markdown display.

    Args:
        rng: ``[start_line, end_line]`` from a symbol result.

    Returns:
        ``"10-34"`` when two elements are present, else ``str(rng)``.
    """
    if len(rng) == 2:
        return f"{rng[0]}-{rng[1]}"
    return str(rng)


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
    added = [(f.path, s) for f in result.files for s in f.added_symbols]
    removed = [(f.path, s) for f in result.files for s in f.removed_symbols]
    modified = [(f.path, s) for f in result.files for s in f.modified_symbols]
    file_scope = [
        (f.path, f.file_scope_changes) for f in result.files if f.file_scope_changes.added_lines or f.file_scope_changes.deleted_lines
    ]

    if added:
        lines.append("Added symbols")
        lines.append("=============")
        lines.append("")
        by_kind: dict[str, list[tuple[str, Any]]] = {}
        for path, sym in added:
            by_kind.setdefault(sym.kind, []).append((path, sym))
        for kind in sorted(by_kind):
            label = kind.capitalize() + "s:"
            lines.append(label)
            for _path, sym in by_kind[kind]:
                lines.append(f"  + {sym.qualified_name}")
            lines.append("")

    if removed:
        lines.append("Removed symbols")
        lines.append("===============")
        lines.append("")
        for path, sym in removed:
            lines.append(f"* {sym.kind} {sym.qualified_name}")
            lines.append(f"  file: {path}")
            lines.append(f"  range: {_format_range(sym.range)}")
            lines.append("")

    if modified:
        lines.append("Modified symbols")
        lines.append("----------------")
        lines.append("")
        by_file: dict[str, list[Any]] = {}
        for path, sym in modified:
            by_file.setdefault(path, []).append(sym)
        for path in sorted(by_file):
            lines.append(path)
            lines.append("")
            for sym in by_file[path]:
                lines.append(f"* {sym.kind} {sym.qualified_name}")
                lines.append(f"  old range: {_format_range(sym.old_range)}")
                lines.append(f"  new range: {_format_range(sym.new_range)}")
                if sym.changed_new_lines:
                    lines.append(f"  changed new lines: {_format_lines(sym.changed_new_lines)}")
                if sym.changed_old_lines:
                    lines.append(f"  changed old lines: {_format_lines(sym.changed_old_lines)}")
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
