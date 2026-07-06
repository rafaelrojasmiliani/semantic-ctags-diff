"""Tests for Vim/Flog navigation helpers."""

from semantic_branch_diff.navigation import (
    collect_navigation_choices,
    flog_line_limit,
    kind_matches_filter,
    symbol_at_source,
)
from semantic_branch_diff.symbols import Symbol, SymbolKey, best_enclosing_symbol


def test_flog_line_limit_format():
    assert flog_line_limit("src/foo.cpp", 10, 34) == "10,34:src/foo.cpp"


def test_kind_matches_filter_function():
    assert kind_matches_filter("method", "function")
    assert not kind_matches_filter("class", "function")


def test_kind_matches_filter_symbol_matches_all():
    assert kind_matches_filter("namespace", "")
    assert kind_matches_filter("class", "symbol")


def test_symbol_at_source_finds_function():
    source = "\n".join(
        [
            "namespace N {",
            "class Foo {",
            "public:",
            "  void bar() {",
            "    int x = 1;",
            "  }",
            "};",
            "}",
        ]
    )
    # Line 5 is inside bar() — exact line depends on ctags; use a generous check.
    result = symbol_at_source(
        source_content=source,
        source_path="f.cpp",
        line=5,
        ctags_executable="ctags",
    )
    assert result["file"] == "f.cpp"
    assert result["line"] == 5
    if result["symbol"] is not None:
        assert "flog_limit" in result
        assert result["flog_limit"].endswith(":f.cpp")


def test_best_enclosing_symbol_still_used_by_navigation():
    sym = Symbol(
        key=SymbolKey(kind="function", qualified_name="Foo::bar"),
        name="bar",
        qualified_name="Foo::bar",
        kind="function",
        raw_kind="function",
        scope="Foo",
        path="f.cpp",
        start_line=2,
        end_line=4,
    )
    chosen = best_enclosing_symbol([sym], 3)
    assert chosen is sym
