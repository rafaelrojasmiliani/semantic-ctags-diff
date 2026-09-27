"""Tests for ctags3_improved indexing (needs ctags on PATH)."""

from ctags3_improved import generate_symbols, index_source

BASE_SOURCE = """\
namespace A::B {
  class Foo {
  public:
    bool isApprox(double x) const { return x > 0; }
    void reset() {}
  };
}
"""

OUT_OF_CLASS_SOURCE = """\
namespace A::B {

bool Foo::isApprox(double x) const {
  return x > 0;
}

void Foo::reset() {}

}
"""


def test_generate_symbols_finds_methods():
    symbols = generate_symbols(
        source_content=BASE_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    names = {s.qualified_name for s in symbols}
    assert "A::B::Foo::isApprox" in names
    assert "A::B::Foo::reset" in names


def test_out_of_class_method_gets_function_kind():
    symbols = generate_symbols(
        source_content=OUT_OF_CLASS_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    approx = next(s for s in symbols if s.name == "isApprox")
    assert approx.kind == "function"
    assert "Foo" in approx.qualified_name


def test_duplicate_qualified_and_unqualified_deduped():
    symbols = generate_symbols(
        source_content=BASE_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    is_approx = [s for s in symbols if s.name == "isApprox"]
    qualified = [s for s in is_approx if "::" in s.qualified_name]
    assert len(qualified) == 1


def test_file_index_scope_links_methods_to_class():
    index = index_source(
        source_content=BASE_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    methods = [s for s in index.symbols if s.name in {"isApprox", "reset"} and s.kind == "function"]
    assert methods
    for method in methods:
        assert method.scope == "A::B::Foo" or method.qualified_name.startswith("A::B::Foo::")
