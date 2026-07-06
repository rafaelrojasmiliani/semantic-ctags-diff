"""Tests for bundled examples and directory snapshot mode."""

from pathlib import Path

from semantic_branch_diff import semantic_diff

EXAMPLE_ROOT = Path(__file__).resolve().parents[1] / "examples" / "01_added_methods"


def test_example_01_directory_snapshot_finds_added_methods():
    """Example 01: header gains declarations; cpp adds out-of-line method bodies."""
    result = semantic_diff(
        old_dir=EXAMPLE_ROOT / "old",
        new_dir=EXAMPLE_ROOT / "new",
        use_pydriller_methods=False,
    )
    assert result.summary["files_changed"] == 2

    header = next(f for f in result.files if f.path.endswith("RobotController.h"))
    # Inline isReady() is a ctags function; reset/configure are declarations only.
    added_qn = {s.qualified_name for s in header.added_symbols}
    assert any(n.endswith("isReady") for n in added_qn)
    assert header.file_scope_changes.added_lines

    cpp = next(f for f in result.files if f.path.endswith("RobotController.cpp"))
    assert cpp.change_type == "add"
    cpp_added = {s.qualified_name for s in cpp.added_symbols}
    assert any(n.endswith("reset") for n in cpp_added)
    assert any(n.endswith("configure") for n in cpp_added)
