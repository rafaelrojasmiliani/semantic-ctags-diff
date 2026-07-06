"""Semantic branch diff package.

Exposes the public API for comparing two Git revisions or directory snapshots
and producing a symbol-level diff of C/C++ sources.
"""

from semantic_branch_diff.diff_engine import SemanticDiffResult, semantic_diff, semantic_diff_directories

__all__ = ["SemanticDiffResult", "semantic_diff", "semantic_diff_directories"]
