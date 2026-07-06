"""Integration tests for semantic diff engine.

Builds temporary Git repos with base ``main`` and working ``feature`` branch,
then asserts added/removed/modified symbols and file-scope changes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from conftest import checkout, commit_all, create_branch, init_repo, run, write_file
from semantic_branch_diff import semantic_diff

BASE_CPP = """\
#include <cmath>

namespace A::B {

bool Foo::isApprox(double x) const {
  return std::abs(x) < 1e-6;
}

void Foo::reset() {
}

}
"""

INCLUDE_CPP = """\
#include <vector>
#include <cmath>

namespace A::B {

bool Foo::isApprox(double x) const {
  return std::abs(x) < 1e-6;
}

}
"""


@pytest.fixture()
def git_repo():
    """Create a repo with ``main`` at base commit and ``feature`` branch checked out.

    Yields:
        Path to the temporary repository root.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        init_repo(repo)
        src = repo / "Source" / "RobotState.cpp"
        write_file(src, BASE_CPP)
        commit_all(repo, "base")
        run(["git", "branch", "-M", "main"], repo)
        create_branch(repo, "feature")
        yield repo


def _diff(repo: Path, head: str = "HEAD") -> object:
    """Run semantic diff from ``main`` to ``head`` with enrichment disabled.

    Args:
        repo: Test repository path.
        head: Head ref (defaults to current branch ``HEAD``).

    Returns:
        :class:`~semantic_branch_diff.diff_engine.SemanticDiffResult`.
    """
    return semantic_diff(
        repo=str(repo),
        base="main",
        head=head,
        use_pydriller_methods=False,
    )


def test_modified_method(git_repo: Path):
    """Body-only edits should classify the method as modified, not added."""
    write_file(
        git_repo / "Source" / "RobotState.cpp",
        BASE_CPP.replace("return std::abs(x) < 1e-6;", "return std::abs(x) < 1e-9;"),
    )
    commit_all(git_repo, "tweak tolerance")

    result = _diff(git_repo)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    modified = {m.qualified_name for m in file.modified_symbols}
    assert any("Foo::isApprox" in name for name in modified)


def test_added_method(git_repo: Path):
    """A new method definition should appear in ``added_symbols``."""
    write_file(
        git_repo / "Source" / "RobotState.cpp",
        BASE_CPP + "\nvoid Foo::configure() {\n}\n",
    )
    commit_all(git_repo, "add configure")

    result = _diff(git_repo)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    added = {s.qualified_name for s in file.added_symbols}
    assert any(name.endswith("configure") for name in added)


def test_removed_method(git_repo: Path):
    """Deleting a method should appear in ``removed_symbols``."""
    write_file(
        git_repo / "Source" / "RobotState.cpp",
        BASE_CPP.replace("void Foo::reset() {\n}\n\n", ""),
    )
    commit_all(git_repo, "remove reset")

    result = _diff(git_repo)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    removed = {s.qualified_name for s in file.removed_symbols}
    assert any(name.endswith("reset") for name in removed)


def test_file_scope_include_change(git_repo: Path):
    """New include lines outside symbols should land in ``file_scope_changes``."""
    write_file(git_repo / "Source" / "RobotState.cpp", INCLUDE_CPP)
    commit_all(git_repo, "add vector include")

    result = _diff(git_repo)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    assert file.file_scope_changes.added_lines
    assert 1 in file.file_scope_changes.added_lines or 2 in file.file_scope_changes.added_lines


def test_namespace_overlap_attributes_method(git_repo: Path):
    """Lines inside a method must attribute to the method, not only namespace."""
    write_file(
        git_repo / "Source" / "RobotState.cpp",
        BASE_CPP.replace("return std::abs(x) < 1e-6;", "return std::abs(x) < 1e-3;"),
    )
    commit_all(git_repo, "body change")

    result = _diff(git_repo)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    assert file.modified_symbols
    sym = file.modified_symbols[0]
    assert sym.kind == "function"
    assert "isApprox" in sym.qualified_name
    assert sym.changed_new_lines


def test_feature_branch_comparison(git_repo: Path):
    """Comparing ``main`` to ``feature`` ref should detect modified symbols."""
    write_file(
        git_repo / "Source" / "RobotState.cpp",
        BASE_CPP.replace("return std::abs(x) < 1e-6;", "return std::abs(x) < 1e-9;"),
    )
    commit_all(git_repo, "feature change")
    checkout(git_repo, "main")

    result = semantic_diff(repo=str(git_repo), base="main", head="feature", use_pydriller_methods=False)
    file = next(f for f in result.files if f.path.endswith("RobotState.cpp"))
    assert file.modified_symbols
