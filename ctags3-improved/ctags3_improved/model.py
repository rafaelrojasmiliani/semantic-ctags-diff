"""Normalized symbol model built on top of classic ctags tags files.

``python-ctags3`` only reads tags rows. This package turns those rows into a
stable, comparable symbol API (kinds, ranges, qualified names, type trees).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


# Lower number = higher priority when a changed line matches overlapping symbols.
KIND_PRIORITY: dict[str, int] = {
    "function": 0,
    "method": 0,
    "constructor": 0,
    "destructor": 0,
    "member": 1,
    "class": 2,
    "struct": 2,
    "interface": 2,
    "enum": 3,
    "union": 3,
    "typedef": 4,
    "namespace": 5,
    "module": 5,
    "package": 5,
    "variable": 6,
    "local": 6,
    "macro": 7,
    "file": 8,
}

# ``member`` is deliberately absent: in ctags it means a class/struct/union DATA
# field, not a method (methods are kind ``f``/``function``).
FUNCTION_KINDS = frozenset({"function", "method", "constructor", "destructor"})
CLASS_KINDS = frozenset({"class", "struct", "interface"})
MEMBER_KINDS = frozenset({"member", "field"})
NOISE_KINDS = frozenset({"variable", "local", "unknown"})


@dataclass(frozen=True)
class SymbolKey:
    """Stable identity for comparing symbols across file revisions."""

    kind: str
    qualified_name: str
    signature: str | None = None


@dataclass
class Symbol:
    """One ctags tag after normalization, with source range and metadata."""

    key: SymbolKey
    name: str
    qualified_name: str
    kind: str
    raw_kind: str
    scope: str
    path: str
    start_line: int
    end_line: int
    file_scope: bool = False
    pattern: str | None = None
    signature: str | None = None

    def range_size(self) -> int:
        """Return inclusive line span length for overlap comparisons."""
        return max(0, self.end_line - self.start_line + 1)

    def contains_line(self, line: int) -> bool:
        """Check whether ``line`` falls inside this symbol's range."""
        return self.start_line <= line <= self.end_line


@dataclass
class TypeDecl:
    """Class/struct/interface view: the type symbol plus its methods and fields."""

    symbol: Symbol
    methods: list[Symbol] = field(default_factory=list)
    members: list[Symbol] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def kind(self) -> str:
        return self.symbol.kind


@dataclass
class FileIndex:
    """Indexed symbols for one source file revision.

    ``symbols`` is the flat source of truth. ``types`` is a derived tree view
    grouping methods/members under enclosing class-like symbols.
    """

    path: str
    symbols: list[Symbol]
    types: dict[str, TypeDecl] = field(default_factory=dict)

    def by_key(self) -> dict[SymbolKey, Symbol]:
        """Index symbols by :class:`SymbolKey` (last wins on duplicate keys)."""
        out: dict[SymbolKey, Symbol] = {}
        for sym in self.symbols:
            out[sym.key] = sym
        return out


def build_type_decls(symbols: Iterable[Symbol]) -> dict[str, TypeDecl]:
    """Group methods and data members under class/struct/interface symbols."""
    types: dict[str, TypeDecl] = {}
    for sym in symbols:
        if sym.kind in CLASS_KINDS:
            types[sym.qualified_name] = TypeDecl(symbol=sym)

    for sym in symbols:
        if sym.kind in CLASS_KINDS:
            continue
        container = sym.scope or (
            sym.qualified_name.rsplit("::", 1)[0] if "::" in sym.qualified_name else ""
        )
        if not container or container not in types:
            continue
        if sym.kind in FUNCTION_KINDS:
            types[container].methods.append(sym)
        elif sym.kind in MEMBER_KINDS:
            types[container].members.append(sym)
    return types
