"""Tests for symbol normalization helpers.

Validates qualified-name building, kind inference, deduplication, and
line-to-symbol matching independent of Git or ctags execution.
"""

from semantic_branch_diff.symbols import (
    Symbol,
    SymbolKey,
    best_enclosing_symbol,
    build_qualified_name,
    deduplicate_symbols,
    effective_kind,
)


def test_effective_kind_empty_becomes_function_for_scoped_method_pattern():
    """Empty ctags kind with method-like pattern should infer ``function``."""
    kind = effective_kind(
        "",
        "A::B::Foo::isApprox",
        "A::B::Foo",
        "/^bool A::B::Foo::isApprox(double x) const {/",
    )
    assert kind == "function"


def test_build_qualified_name_from_class_field():
    """Class field from ctags should prefix unqualified method names."""
    qn = build_qualified_name("isApprox", "", class_field="A::B::Foo")
    assert qn == "A::B::Foo::isApprox"


def test_build_qualified_name_avoids_duplicate_scope():
    """Already-qualified names must not get double scope prefixes."""
    qn = build_qualified_name("A::B::Foo::isApprox", "A::B::Foo")
    assert qn == "A::B::Foo::isApprox"


def test_deduplicate_prefers_qualified_symbol():
    """Qualified and unqualified duplicates at same range keep the qualified tag."""
    common_key = SymbolKey(kind="function", qualified_name="A::B::Foo::isApprox")
    unqualified = Symbol(
        key=SymbolKey(kind="function", qualified_name="isApprox"),
        name="isApprox",
        qualified_name="isApprox",
        kind="function",
        raw_kind="function",
        scope="",
        path="f.cpp",
        start_line=4,
        end_line=8,
    )
    qualified = Symbol(
        key=common_key,
        name="isApprox",
        qualified_name="A::B::Foo::isApprox",
        kind="function",
        raw_kind="function",
        scope="A::B::Foo",
        path="f.cpp",
        start_line=4,
        end_line=8,
    )
    result = deduplicate_symbols([unqualified, qualified])
    names = [s.qualified_name for s in result]
    assert "isApprox" not in names
    assert "A::B::Foo::isApprox" in names


def test_best_enclosing_symbol_prefers_method_over_namespace():
    """Changed lines inside a method must not be attributed only to namespace."""
    ns = Symbol(
        key=SymbolKey(kind="namespace", qualified_name="A::B"),
        name="B",
        qualified_name="A::B",
        kind="namespace",
        raw_kind="namespace",
        scope="A",
        path="f.cpp",
        start_line=1,
        end_line=20,
    )
    method = Symbol(
        key=SymbolKey(kind="function", qualified_name="A::B::Foo::isApprox"),
        name="isApprox",
        qualified_name="A::B::Foo::isApprox",
        kind="function",
        raw_kind="function",
        scope="A::B::Foo",
        path="f.cpp",
        start_line=4,
        end_line=8,
    )
    chosen = best_enclosing_symbol([ns, method], 6)
    assert chosen is not None
    assert chosen.qualified_name == "A::B::Foo::isApprox"
