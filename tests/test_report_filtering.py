"""Tests for report noise reduction.

Branch reports were dominated by three kinds of noise: ctags data members
listed as methods, locals and free variables, and symbols whose qualified name
contains a generated anonymous scope. These tests pin the fixes.
"""

from semantic_branch_diff.diff_engine import (
    FileDiffResult,
    FileScopeChanges,
    ModifiedSymbolResult,
    SemanticDiffResult,
    SymbolSummary,
)
from semantic_branch_diff.renderers import render_markdown
from semantic_branch_diff.symbols import (
    FUNCTION_KINDS,
    effective_kind,
    is_anonymous,
    is_reportable,
    symbol_key_from_tag_fields,
)


def _tag_kind(raw_kind: str, *, class_field: str = "", namespace_field: str = "") -> str:
    """Return the normalized kind ctags row would produce."""
    key, _name, _scope = symbol_key_from_tag_fields(
        name="value",
        raw_kind=raw_kind,
        scope=class_field or namespace_field,
        class_field=class_field,
        namespace_field=namespace_field,
        enum_field="",
        interface_field="",
        pattern="/^  double value;$/",
        _file_scope=False,
    )
    return key.kind


def test_ctags_member_is_a_data_field_not_a_method():
    """ctags kind 'm' means a data member; it must not be reported as a method."""
    assert effective_kind("m", "DeltaTime", "Params", "/^  double DeltaTime;$/") == "member"
    assert effective_kind("member", "dt", "Params", "/^  double dt;$/") == "member"
    # A data field is not callable, so it must stay out of the function family.
    assert "member" not in FUNCTION_KINDS


def test_member_of_a_class_stays_a_member():
    """A member with a class-like container is a genuine field."""
    assert _tag_kind("m", class_field="ImFusion::Robotics::Params") == "member"


def test_member_of_a_namespace_is_really_a_variable():
    """Some ctags flavors tag namespace-scope variables as members too."""
    assert _tag_kind("m", namespace_field="ImFusion::Robotics") == "variable"


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


def _summary(kind: str, qualified_name: str, classification: str = "added") -> SymbolSummary:
    return SymbolSummary(
        kind=kind,
        qualified_name=qualified_name,
        name=qualified_name.split("::")[-1],
        scope="",
        file="",
        range=[10, 20],
        classification=classification,
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
    ns = _summary("namespace", "ImFusion::Robotics")
    files = [
        _file("a.cpp", added=[ns, _summary("local", "angleRad")]),
        _file("b.cpp", added=[ns, _summary("namespace", "ImFusion::Robotics::__anon37a8102f0111")]),
        _file("c.cpp", added=[ns]),
    ]
    out = render_markdown(_result(files))

    assert out.count("+ ImFusion::Robotics\n") == 1
    assert "angleRad" not in out
    assert "__anon" not in out


def test_markdown_members_are_not_listed_as_methods():
    """Data fields get their own heading instead of landing under Methods."""
    out = render_markdown(_result([_file("a.h", added=[_summary("member", "Params::DeltaTime")])]))
    assert "Members:" in out
    assert "Methods:" not in out


def test_markdown_removed_and_modified_show_names_only():
    """No file or line noise: the Vim report resolves those from the JSON."""
    modified = ModifiedSymbolResult(
        kind="function",
        qualified_name="ImFusion::Robotics::RobotControl::update",
        name="update",
        scope="",
        file="src/RobotControl.cpp",
        old_range=[11, 329],
        new_range=[11, 330],
        changed_old_lines=[32, 39, 40],
        changed_new_lines=[32, 33, 40],
        classification="modified",
    )
    out = render_markdown(
        _result(
            [
                _file(
                    "src/RobotControl.cpp",
                    removed=[_summary("function", "ImFusion::Robotics::Base::cloneTyped")],
                    modified=[modified],
                )
            ]
        )
    )

    assert "- ImFusion::Robotics::Base::cloneTyped" in out
    assert "~ function ImFusion::Robotics::RobotControl::update" in out
    # The verbose per-symbol detail is gone.
    for noise in ("range:", "changed new lines:", "changed old lines:", "file:"):
        assert noise not in out
