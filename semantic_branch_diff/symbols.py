"""Backward-compatible re-exports from ctags3-improved.

Symbol model and ctags enrichment live in the ``ctags3-improved`` package.
This module keeps existing ``semantic_branch_diff.symbols`` import paths working.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ctags3_improved import (  # noqa: F401 — re-export public surface
    CLASS_KINDS,
    FUNCTION_KINDS,
    KIND_PRIORITY,
    MEMBER_KINDS,
    NOISE_KINDS,
    Symbol,
    SymbolChange,
    SymbolKey,
    best_enclosing_symbol,
    build_qualified_name,
    deduplicate_symbols,
    effective_kind,
    is_anonymous,
    is_reportable,
    kind_priority,
    normalize_scope_parts,
    symbol_change,
)

__all__ = [
    "CLASS_KINDS",
    "FUNCTION_KINDS",
    "KIND_PRIORITY",
    "LineAttribution",
    "MEMBER_KINDS",
    "NOISE_KINDS",
    "Symbol",
    "SymbolChange",
    "SymbolKey",
    "best_enclosing_symbol",
    "build_qualified_name",
    "deduplicate_symbols",
    "effective_kind",
    "is_anonymous",
    "is_reportable",
    "kind_priority",
    "normalize_scope_parts",
    "symbol_change",
]


@dataclass
class LineAttribution:
    """Accumulator mapping changed lines to symbols or file scope (diff-engine)."""

    symbol_keys: set[SymbolKey] = field(default_factory=set)
    file_scope_lines: list[int] = field(default_factory=list)

    def add_line(self, line: int, symbol: Symbol | None) -> None:
        if symbol is None:
            self.file_scope_lines.append(line)
        else:
            self.symbol_keys.add(symbol.key)
