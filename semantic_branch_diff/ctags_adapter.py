"""Backward-compatible re-exports from ctags3-improved.

Ctags execution and tags parsing live in ``ctags3_improved.adapter``.
"""

from ctags3_improved import (  # noqa: F401
    CtagsError,
    FileIndex,
    TypeDecl,
    generate_symbols,
    index_source,
    require_ctags_executable,
    require_ctags_library,
    symbols_by_key,
)

__all__ = [
    "CtagsError",
    "FileIndex",
    "TypeDecl",
    "generate_symbols",
    "index_source",
    "require_ctags_executable",
    "require_ctags_library",
    "symbols_by_key",
]
