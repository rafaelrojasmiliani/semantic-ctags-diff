"""Tests for ctags parsing.

Exercises :func:`~semantic_branch_diff.ctags_adapter.generate_symbols` against
in-memory C++ snippets without a Git repository.
"""

from semantic_branch_diff.ctags_adapter import generate_symbols

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
    """In-class method definitions should produce qualified function symbols."""
    symbols = generate_symbols(
        source_content=BASE_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    names = {s.qualified_name for s in symbols}
    assert "A::B::Foo::isApprox" in names
    assert "A::B::Foo::reset" in names


def test_out_of_class_method_gets_function_kind():
    """Out-of-class definitions with empty kind should still be ``function``."""
    symbols = generate_symbols(
        source_content=OUT_OF_CLASS_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    approx = next(s for s in symbols if s.name == "isApprox")
    assert approx.kind == "function"
    assert "Foo" in approx.qualified_name


def test_duplicate_qualified_and_unqualified_deduped():
    """Only one ``isApprox`` symbol should remain after deduplication."""
    symbols = generate_symbols(
        source_content=BASE_SOURCE,
        source_path="RobotState.cpp",
        ctags_executable="ctags",
    )
    is_approx = [s for s in symbols if s.name == "isApprox"]
    qualified = [s for s in is_approx if "::" in s.qualified_name]
    assert len(qualified) == 1
