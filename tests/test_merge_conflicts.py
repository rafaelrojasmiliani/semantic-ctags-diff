"""Tests for merge-conflict detection (``--merge-conflicts``)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from conftest import checkout, commit_all, create_branch, init_repo, run, write_file
from semantic_branch_diff.cli import main
from semantic_branch_diff.merge_conflicts import find_merge_conflicts

LINES = "".join(f"line {i}\n" for i in range(1, 11))


def _repo(tmp: str) -> Path:
    """``main`` and ``feature`` diverge so that every conflict kind appears once."""
    repo = Path(tmp) / "repo"
    init_repo(repo)
    write_file(repo / "conflict.cpp", LINES)
    write_file(repo / "clean.cpp", LINES)
    write_file(repo / "gone.cpp", LINES)
    write_file(repo / "both_gone.cpp", LINES)
    commit_all(repo, "base")
    run(["git", "branch", "-M", "main"], repo)

    create_branch(repo, "feature")
    write_file(repo / "conflict.cpp", LINES.replace("line 5", "feature 5"))
    write_file(repo / "clean.cpp", LINES.replace("line 1\n", "feature 1\n"))
    write_file(repo / "gone.cpp", LINES.replace("line 2", "feature 2"))
    write_file(repo / "new.cpp", "feature\n")
    (repo / "both_gone.cpp").unlink()
    commit_all(repo, "feature")

    checkout(repo, "main")
    write_file(repo / "conflict.cpp", LINES.replace("line 5", "main 5"))
    write_file(repo / "clean.cpp", LINES.replace("line 10", "main 10"))
    (repo / "gone.cpp").unlink()
    write_file(repo / "new.cpp", "main\n")
    (repo / "both_gone.cpp").unlink()
    commit_all(repo, "main")
    return repo


def test_detects_each_conflict_kind_and_skips_clean_merges():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        result = find_merge_conflicts(repo, "HEAD", "feature")

        assert {(c.path, c.kind) for c in result.conflicts} == {
            ("conflict.cpp", "content"),
            ("gone.cpp", "modify/delete"),
            ("new.cpp", "add/add"),
        }
        assert result.merge_base == run(["git", "merge-base", "main", "feature"], repo).strip()


def test_cli_emits_json(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        repo = _repo(tmp)
        code = main(["--repo", str(repo), "--base", "HEAD", "--head", "feature", "--merge-conflicts"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["theirs"] == "feature"
        assert [c["path"] for c in data["conflicts"]] == ["conflict.cpp", "gone.cpp", "new.cpp"]
