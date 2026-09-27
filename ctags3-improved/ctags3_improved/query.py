"""Queries over normalized symbol lists."""

from __future__ import annotations

from collections.abc import Iterable

from ctags3_improved.model import KIND_PRIORITY, Symbol, SymbolKey


def kind_priority(kind: str) -> int:
    """Return sort priority for symbol kind (lower = more specific)."""
    return KIND_PRIORITY.get(kind, 99)


def best_enclosing_symbol(symbols: list[Symbol], line: int) -> Symbol | None:
    """Pick the innermost, highest-priority symbol containing ``line``."""
    candidates = [s for s in symbols if s.contains_line(line) and not s.file_scope]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: (kind_priority(s.kind), s.range_size(), s.start_line),
    )


def symbols_by_key(symbols: list[Symbol]) -> dict[SymbolKey, Symbol]:
    """Index symbols by their normalized :class:`SymbolKey`."""
    out: dict[SymbolKey, Symbol] = {}
    for sym in symbols:
        out[sym.key] = sym
    return out


def deduplicate_symbols(symbols: Iterable[Symbol]) -> list[Symbol]:
    """Remove duplicate ctags rows for the same logical symbol."""
    by_qualified: dict[tuple[str, str, int], Symbol] = {}
    for sym in symbols:
        bucket = (sym.kind, sym.qualified_name, sym.start_line)
        existing = by_qualified.get(bucket)
        if existing is None:
            by_qualified[bucket] = sym
            continue
        if _symbol_preference(sym, existing):
            by_qualified[bucket] = sym

    result = list(by_qualified.values())
    filtered: list[Symbol] = []
    for sym in result:
        if any(
            other is not sym
            and other.kind == sym.kind
            and other.start_line == sym.start_line
            and other.end_line == sym.end_line
            and "::" in other.qualified_name
            and "::" not in sym.qualified_name
            for other in result
        ):
            continue
        filtered.append(sym)
    return filtered


def _symbol_preference(candidate: Symbol, incumbent: Symbol) -> bool:
    if "::" in candidate.qualified_name and "::" not in incumbent.qualified_name:
        return True
    c_pri = KIND_PRIORITY.get(candidate.kind, 99)
    i_pri = KIND_PRIORITY.get(incumbent.kind, 99)
    if c_pri != i_pri:
        return c_pri < i_pri
    return candidate.range_size() <= incumbent.range_size()
