"""Tests for report noise reduction.

Branch reports were dominated by three kinds of noise: ctags data members
listed as methods, locals and free variables, and symbols whose qualified name
contains a generated anonymous scope. These tests pin the fixes.
"""

from ctags3_improved import Symbol, SymbolChange, SymbolKey

from semantic_branch_diff.diff_engine import (
    FileDiffResult,
    FileScopeChanges,
    SemanticDiffResult,
)
from semantic_branch_diff.renderers import render_markdown
from semantic_branch_diff.symbols import (
    FUNCTION_KINDS,
    effective_kind,
    is_anonymous,
    is_reportable,
)


def test_ctags_member_is_a_data_field_not_a_method():
    """ctags kind 'm' means a data member; it must not be reported as a method."""
    assert effective_kind("m", "DeltaTime", "Params", "/^  double DeltaTime;$/") == "member"
    assert effective_kind("member", "dt", "Params", "/^  double dt;$/") == "member"
    # A data field is not callable, so it must stay out of the function family.
    assert "member" not in FUNCTION_KINDS


def test_locals_and_variables_are_not_reportable():
    """Locals and free variables are too granular for a branch report."""
    assert not is_reportable("local", "angleRad")
    assert not is_reportable("variable", "ImFusion::Robotics::motionGenerator")
    assert is_reportable("member", "ImFusion::Robotics::Params::DeltaTime")
    assert is_reportable("function", "ImFusion::Robotics::Params::reset")


def test_anonymous_namespace_symbols_are_filtered():
    """Generated __anon names differ between revisions and mean nothing."""
    assert is_anonymous("ImFusion::Robotics::__anon37a8102f0111")
    assert is_anonymous("__anon37a8102f0111::HOLD_TOLERANCE")
    assert not is_reportable("namespace", "ImFusion::Robotics::__anon37a8102f0111")
    # Nested anonymous scopes, and the bare segment as the symbol itself.
    assert is_anonymous("ImFusion::Robotics::__anon37a8102f0111::IcmpHeader::__anon37a8102f0203")
    assert is_anonymous("__anon37a8102f0302")
    # Exuberant numbers them from 1 instead of hashing.
    assert is_anonymous("ImFusion::__anon1::Helper")


def test_real_identifiers_starting_with_anon_are_kept():
    """Only 'anon' followed by nothing but hex is a generated scope."""
    assert not is_anonymous("ImFusion::Robotics::TestUtils")
    assert not is_anonymous("ImFusion::Robotics::anonymize")
    assert not is_anonymous("ImFusion::AnonymousPose")
    assert is_reportable("class", "ImFusion::AnonymousPose")


def _sym(kind: str, qualified_name: str, *, path: str = "", start: int = 10, end: int = 20) -> Symbol:
    name = qualified_name.split("::")[-1]
    return Symbol(
        key=SymbolKey(kind=kind, qualified_name=qualified_name),
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        raw_kind=kind,
        scope="",
        path=path,
        start_line=start,
        end_line=end,
    )


def _result(files: list[FileDiffResult]) -> SemanticDiffResult:
    return SemanticDiffResult(
        repo="/tmp/repo",
        base_ref="devel",
        head_ref="HEAD",
        merge_base="abc",
        head_commit="def",
        files=files,
        summary={},
    )


def _file(path: str, **kwargs) -> FileDiffResult:
    return FileDiffResult(
        path=path,
        old_path=None,
        change_type="modified",
        language="cpp",
        added_lines=[],
        deleted_lines=[],
        added_symbols=kwargs.get("added", []),
        removed_symbols=kwargs.get("removed", []),
        modified_symbols=kwargs.get("modified", []),
        file_scope_changes=FileScopeChanges(added_lines=[], deleted_lines=[]),
    )


def test_markdown_drops_noise_and_repeats():
    """The same namespace reopened in many files is listed once, not per file."""
    ns = _sym("namespace", "ImFusion::Robotics")
    files = [
        _file("a.cpp", added=[ns, _sym("local", "angleRad")]),
        _file("b.cpp", added=[ns, _sym("namespace", "ImFusion::Robotics::__anon37a8102f0111")]),
        _file("c.cpp", added=[ns]),
    ]
    out = render_markdown(_result(files))

    assert out.count("+ ImFusion::Robotics\n") == 1
    assert "angleRad" not in out
    assert "__anon" not in out


def test_markdown_members_are_not_listed_as_methods():
    """Data fields get their own heading instead of landing under Methods."""
    out = render_markdown(_result([_file("a.h", added=[_sym("member", "Params::DeltaTime")])]))
    assert "Members:" in out
    assert "Methods:" not in out


def test_markdown_removed_and_modified_show_names_only():
    """No file or line noise: the Vim report resolves those from the JSON."""
    qn = "ImFusion::Robotics::RobotControl::update"
    modified = SymbolChange(
        old=_sym("function", qn, path="src/RobotControl.cpp", start=11, end=329),
        new=_sym("function", qn, path="src/RobotControl.cpp", start=11, end=330),
        deleted_lines=[32, 39, 40],
        added_lines=[32, 33, 40],
    )
    out = render_markdown(
        _result(
            [
                _file(
                    "src/RobotControl.cpp",
                    removed=[_sym("function", "ImFusion::Robotics::Base::cloneTyped")],
                    modified=[modified],
                )
            ]
        )
    )

    assert "- ImFusion::Robotics::Base::cloneTyped" in out
    # Modified symbols are grouped by kind like the others, with no kind prefix
    # on the bullet and no per-file heading.
    assert "~ ImFusion::Robotics::RobotControl::update" in out
    assert "~ function " not in out
    assert "src/RobotControl.cpp\n\n  ~" not in out
    # The verbose per-symbol detail is gone.
    for noise in ("range:", "changed new lines:", "changed old lines:", "file:"):
        assert noise not in out


def test_markdown_lists_changed_files_before_the_symbol_sections():
    """A git --name-status style list, so deleted files are visible too."""
    files = [
        _file("src/kept.cpp"),
        _file("src/gone.cpp"),
        _file("src/new.cpp"),
    ]
    files[1].change_type = "delete"
    files[2].change_type = "add"
    out = render_markdown(_result(files))

    assert "  D src/gone.cpp" in out
    assert "  A src/new.cpp" in out
    assert out.index("Changed files") < out.index("src/kept.cpp")


def test_markdown_has_no_file_scope_section():
    """File-scope line noise is not reported any more."""
    f = _file("src/a.cpp")
    f.file_scope_changes = FileScopeChanges(added_lines=[5, 6], deleted_lines=[9])
    out = render_markdown(_result([f]))

    assert "File-scope changes" not in out
    assert "added lines:" not in out
