"""Semantic branch diff package.

Exposes the public API for comparing two Git branches and producing a
symbol-level diff of C/C++ sources. Used by the CLI (``semantic-branch-diff``)
and by external tools such as Vim/Fugitive wrappers.

Typical usage::

    from semantic_branch_diff import semantic_diff

    result = semantic_diff(repo="/path/to/repo", base="main", head="HEAD")
    print(result.to_dict())
"""

from semantic_branch_diff.diff_engine import SemanticDiffResult, semantic_diff

__all__ = ["SemanticDiffResult", "semantic_diff"]
