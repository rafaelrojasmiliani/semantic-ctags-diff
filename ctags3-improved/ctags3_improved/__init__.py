"""ctags3-improved — enriched symbol API on top of python-ctags3.

python-ctags3 reads classic tags files. This package runs ctags, normalizes
kinds/names/ranges, and exposes :class:`FileIndex` / :class:`Symbol`.
"""

from ctags3_improved.adapter import (
    CtagsError,
    generate_symbols,
    index_source,
    require_ctags_executable,
    require_ctags_library,
)
from ctags3_improved.change import SymbolChange, symbol_change
from ctags3_improved.model import (
    CLASS_KINDS,
    FUNCTION_KINDS,
    KIND_PRIORITY,
    MEMBER_KINDS,
    NOISE_KINDS,
    FileIndex,
    Symbol,
    SymbolKey,
)
from ctags3_improved.normalize import (
    build_qualified_name,
    effective_kind,
    is_anonymous,
    is_reportable,
    normalize_scope_parts,
)
from ctags3_improved.query import (
    best_enclosing_symbol,
    deduplicate_symbols,
    kind_priority,
    symbols_by_key,
)

__all__ = [
    "CLASS_KINDS",
    "CtagsError",
    "FUNCTION_KINDS",
    "FileIndex",
    "KIND_PRIORITY",
    "MEMBER_KINDS",
    "NOISE_KINDS",
    "Symbol",
    "SymbolChange",
    "SymbolKey",
    "best_enclosing_symbol",
    "build_qualified_name",
    "deduplicate_symbols",
    "effective_kind",
    "generate_symbols",
    "index_source",
    "is_anonymous",
    "is_reportable",
    "kind_priority",
    "normalize_scope_parts",
    "require_ctags_executable",
    "require_ctags_library",
    "symbol_change",
    "symbols_by_key",
]
