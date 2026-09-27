"""Compatibility shim — normalization tests live in ctags3-improved."""

from ctags3_improved import (  # noqa: F401
    Symbol,
    SymbolKey,
    best_enclosing_symbol,
    build_qualified_name,
    deduplicate_symbols,
    effective_kind,
)
