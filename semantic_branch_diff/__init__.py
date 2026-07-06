"""Semantic branch diff package.

Exposes the public API for comparing two Git revisions or directory snapshots
and producing a symbol-level diff of C/C++ sources.
"""

from semantic_branch_diff.diff_engine import SemanticDiffResult, semantic_diff, semantic_diff_directories
from semantic_branch_diff.navigation import (
    best_symbol_for_line,
    collect_navigation_choices,
    flog_line_limit,
    symbol_at_path,
    symbol_at_source,
)

__all__ = [
    "SemanticDiffResult",
    "best_symbol_for_line",
    "collect_navigation_choices",
    "flog_line_limit",
    "semantic_diff",
    "semantic_diff_directories",
    "symbol_at_path",
    "symbol_at_source",
]
