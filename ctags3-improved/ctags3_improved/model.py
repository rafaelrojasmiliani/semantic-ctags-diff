"""Normalized symbol model built on top of classic ctags tags files.

``python-ctags3`` only reads tags rows. This package turns those rows into a
stable, comparable symbol API (kinds, ranges, qualified names).
"""

from __future__ import annotations

from dataclasses import dataclass


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
    """Stable identity for comparing symbols across file revisions.

    Attributes:
        kind: Normalized kind (``function``, ``class``, …). Part of identity so
            a function and a type with the same name do not collide.
        qualified_name: Fully qualified C++ name when available.
        signature: Optional ctags pattern fingerprint for signature changes.
    """

    kind: str
    qualified_name: str
    signature: str | None = None


@dataclass
class Symbol:
    """One ctags tag after normalization, with source range and metadata.

    Ctags is per-file: a class tag's range covers only the header (or whatever
    file was indexed). Out-of-line method bodies in a ``.cpp`` are separate
    :class:`Symbol` rows in that translation unit, linked by ``scope`` /
    ``qualified_name``, not nested under the class object.

    Attributes:
        key: Identity used for added/removed/modified set comparisons.
        name: Short unqualified name (last ``::`` segment), e.g. ``isApprox``.
        qualified_name: Full name used in reports, e.g. ``A::B::Foo::isApprox``.
        kind: Normalized kind (may differ from ``raw_kind``); see
            :data:`FUNCTION_KINDS`, :data:`CLASS_KINDS`, :data:`MEMBER_KINDS`.
        raw_kind: Kind string straight from the tags file (``f``, ``function``,
            or empty when ctags omitted it).
        scope: Enclosing qualifier after normalization (parent class/namespace
            string, e.g. ``A::B::Foo``). Empty for file-level / free symbols.
            This is the parent link — not a second inventory of children.
        path: Repo-relative path of the file this tag was extracted from.
        start_line: 1-based start line (inclusive) in ``path``.
        end_line: 1-based end line (inclusive); inferred from braces when ctags
            omits ``end:``.
        file_scope: True for file-level / static tags that should not steal
            line attribution from nested symbols.
        pattern: Original ctags search pattern (``/^…$/``), if present.
        signature: Pattern fingerprint used as a signature hint (often the same
            as ``pattern``); also stored on :attr:`key.signature`.
    """

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

    def same_identity(self, other: Symbol) -> bool:
        """True when both symbols share the same :class:`SymbolKey`."""
        return self.key == other.key

    def contains_symbol(self, other: Symbol) -> bool:
        """True when ``other``'s range is nested in this one (same path)."""
        if self.path != other.path:
            return False
        return self.start_line <= other.start_line and other.end_line <= self.end_line

    def diff_against(
        self,
        new: Symbol,
        *,
        deleted_lines: list[int],
        added_lines: list[int],
    ):
        """Compare this (old) symbol to ``new``; see :func:`ctags3_improved.change.symbol_change`."""
        from ctags3_improved.change import symbol_change

        return symbol_change(
            self,
            new,
            deleted_lines=deleted_lines,
            added_lines=added_lines,
        )


@dataclass
class FileIndex:
    """Indexed symbols for one source file revision.

    ``symbols`` is a flat list (one entry per ctags tag). Parent/child
    relationships are expressed via :attr:`Symbol.scope` and
    :attr:`Symbol.qualified_name`, not a separate type tree.
    """

    path: str
    symbols: list[Symbol]

    def by_key(self) -> dict[SymbolKey, Symbol]:
        """Index symbols by :class:`SymbolKey` (last wins on duplicate keys)."""
        out: dict[SymbolKey, Symbol] = {}
        for sym in self.symbols:
            out[sym.key] = sym
        return out
