"""Symbol-level change between two inventories (pure, no Git)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ctags3_improved.model import Symbol, SymbolKey


def _lines_in_range(lines: list[int], start: int, end: int) -> list[int]:
    return sorted({ln for ln in lines if start <= ln <= end})


def _signature_changed(old: Symbol, new: Symbol) -> bool:
    if old.pattern and new.pattern and old.pattern != new.pattern:
        return True
    return bool(old.signature and new.signature and old.signature != new.signature)


@dataclass
class SymbolChange:
    """A symbol present in both revisions whose body or signature changed.

    Attributes:
        old: Symbol at the base revision.
        new: Symbol at the head revision (same identity for inventory matching).
        deleted_lines: Deleted diff lines intersecting ``old``'s range.
        added_lines: Added diff lines intersecting ``new``'s range.
        pydriller: Optional enrichment from the semantic-diff layer (empty here).
    """

    old: Symbol
    new: Symbol
    deleted_lines: list[int]
    added_lines: list[int]
    pydriller: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> SymbolKey:
        return self.new.key

    @property
    def kind(self) -> str:
        return self.new.kind

    @property
    def qualified_name(self) -> str:
        return self.new.qualified_name

    @property
    def name(self) -> str:
        return self.new.name

    @property
    def scope(self) -> str:
        return self.new.scope

    @property
    def old_range(self) -> list[int]:
        return [self.old.start_line, self.old.end_line]

    @property
    def new_range(self) -> list[int]:
        return [self.new.start_line, self.new.end_line]

    # Aliases matching the former ModifiedSymbolResult field names.
    @property
    def changed_old_lines(self) -> list[int]:
        return self.deleted_lines

    @property
    def changed_new_lines(self) -> list[int]:
        return self.added_lines


def symbol_change(
    old: Symbol,
    new: Symbol,
    *,
    deleted_lines: list[int],
    added_lines: list[int],
    pydriller: dict[str, Any] | None = None,
) -> SymbolChange | None:
    """Return a :class:`SymbolChange` if ``old``/``new`` differ by lines or signature.

    Returns:
        ``None`` when there is no intersecting line change and no signature change.
    """
    changed_old = _lines_in_range(deleted_lines, old.start_line, old.end_line)
    changed_new = _lines_in_range(added_lines, new.start_line, new.end_line)
    if not changed_old and not changed_new and not _signature_changed(old, new):
        return None
    return SymbolChange(
        old=old,
        new=new,
        deleted_lines=changed_old,
        added_lines=changed_new,
        pydriller=pydriller or {},
    )
