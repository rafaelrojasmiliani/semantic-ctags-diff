"""Files that would conflict when merging two refs.

Works on blobs only: no checkout, no index, no merge commit. For every path
changed on both sides since the merge base, the three versions go through
``git merge-file``; a non-zero exit means the merge would stop on that file.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from semantic_branch_diff import git_utils


@dataclass
class MergeConflict:
    """One conflicting path.

    Attributes:
        path: Repo-relative path.
        kind: ``content`` (both modified), ``add/add`` (both added with
            different text) or ``modify/delete`` (one side deleted it).
    """

    path: str
    kind: str


@dataclass
class MergeConflicts:
    """Conflicts of merging ``theirs`` into ``ours``."""

    repo: str
    ours: str
    theirs: str
    ours_commit: str
    theirs_commit: str
    merge_base: str
    conflicts: list[MergeConflict]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _changes(repo: Path, base: str, ref: str) -> dict[str, str]:
    """Map path -> git status letter (A/M/D/T) for ``base..ref``."""
    out = git_utils.run_git(repo, "diff", "--name-status", "--no-renames", base, ref)
    changes: dict[str, str] = {}
    for line in out.splitlines():
        if line.strip():
            status, path = line.split("\t", 1)
            changes[path] = status[0]
    return changes


def _blob(repo: Path, ref: str, path: str) -> bytes:
    """Raw bytes of ``ref:path`` (binary-safe), ``b""`` when absent."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else b""


def _merges_cleanly(ours: bytes, base: bytes, theirs: bytes) -> bool:
    if ours == theirs:
        return True
    with tempfile.TemporaryDirectory(prefix="semantic_merge_") as tmp:
        files = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            f = Path(tmp) / name
            f.write_bytes(data)
            files.append(str(f))
        # Exit > 0 counts conflict hunks; < 0 (e.g. binary input) is an error.
        # Either way git would not merge the file on its own.
        proc = subprocess.run(
            ["git", "merge-file", "-p", "-q", *files],
            capture_output=True,
            check=False,
        )
    return proc.returncode == 0


def find_merge_conflicts(repo: str | Path, ours: str, theirs: str) -> MergeConflicts:
    """List files that would conflict when merging ``theirs`` into ``ours``.

    ponytail: renames are not followed (``--no-renames``), so a file renamed on
    one side and edited on the other shows as modify/delete, and a clean
    rename+edit git would resolve is not detected either way. Upgrade path:
    ``git merge-tree --write-tree --name-only`` once git >= 2.38 is required.
    """
    root = git_utils.resolve_repo_root(repo)
    ours_commit = git_utils.rev_parse(root, ours)
    theirs_commit = git_utils.rev_parse(root, theirs)
    base = git_utils.merge_base(root, ours_commit, theirs_commit)

    ours_changes = _changes(root, base, ours_commit)
    theirs_changes = _changes(root, base, theirs_commit)

    conflicts: list[MergeConflict] = []
    for path in sorted(ours_changes.keys() & theirs_changes.keys()):
        statuses = {ours_changes[path], theirs_changes[path]}
        if statuses == {"D"}:
            continue
        if "D" in statuses:
            conflicts.append(MergeConflict(path, "modify/delete"))
            continue
        if not _merges_cleanly(
            _blob(root, ours_commit, path),
            _blob(root, base, path),
            _blob(root, theirs_commit, path),
        ):
            conflicts.append(MergeConflict(path, "add/add" if statuses == {"A"} else "content"))

    return MergeConflicts(
        repo=str(root),
        ours=ours,
        theirs=theirs,
        ours_commit=ours_commit,
        theirs_commit=theirs_commit,
        merge_base=base,
        conflicts=conflicts,
    )
