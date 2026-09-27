"""Minimal checks for SymbolChange / symbol_change."""

from ctags3_improved import Symbol, SymbolKey, symbol_change


def _sym(qn: str, *, start: int, end: int, pattern: str | None = None) -> Symbol:
    kind = "function"
    return Symbol(
        key=SymbolKey(kind=kind, qualified_name=qn, signature=pattern),
        name=qn.split("::")[-1],
        qualified_name=qn,
        kind=kind,
        raw_kind=kind,
        scope="",
        path="f.cpp",
        start_line=start,
        end_line=end,
        pattern=pattern,
        signature=pattern,
    )


def test_symbol_change_none_when_no_overlap():
    old = _sym("Foo::bar", start=10, end=20)
    new = _sym("Foo::bar", start=10, end=20)
    assert symbol_change(old, new, deleted_lines=[1], added_lines=[2]) is None


def test_symbol_change_intersects_lines():
    old = _sym("Foo::bar", start=10, end=20)
    new = _sym("Foo::bar", start=10, end=22)
    change = symbol_change(old, new, deleted_lines=[12], added_lines=[21])
    assert change is not None
    assert change.deleted_lines == [12]
    assert change.added_lines == [21]
    assert change.old_range == [10, 20]
    assert change.new_range == [10, 22]
    assert change.changed_old_lines == change.deleted_lines
    assert change.changed_new_lines == change.added_lines


def test_diff_against_delegates():
    new = _sym("Foo::bar", start=10, end=20, pattern="/^void bar();$/")
    # Signature-only change (patterns differ).
    old = _sym("Foo::bar", start=10, end=20, pattern="/^int bar();$/")
    change = old.diff_against(new, deleted_lines=[], added_lines=[])
    assert change is not None
    assert change.old is old
    assert change.new is new
