"""Git subprocess helpers for branch comparison.

Wraps ``git`` CLI calls used by the diff engine to resolve refs, list changed
files, fetch blob content, and parse unified diffs. PyDriller is not required
here; subprocess git gives precise merge-base..head semantics for PR-style diffs.

Also provides :func:`diff_texts` for line-level diffs between arbitrary strings
(used by directory snapshot mode in examples).
"""

from __future__ import annotations

import difflib
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(RuntimeError):
    """Raised when a git subprocess exits with a non-zero status."""


def run_git(repo: str | Path, *args: str, check: bool = True) -> str:
    """Run ``git -C <repo> <args>`` and return stdout.

    Base primitive for all git operations in this package. Uses ``-C`` so the
    tool works when ``repo`` is a submodule path or any directory inside a
    worktree.

    Args:
        repo: Repository path passed to ``git -C``.
        *args: Remaining git subcommand and flags.
        check: When ``True``, raise :class:`GitError` on non-zero exit.

    Returns:
        Stripped stdout text from the git process.

    Raises:
        GitError: If ``check`` is ``True`` and git fails.
    """
    cmd = ["git", "-C", str(repo), *args]
    logger.debug("running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise GitError(stderr or f"git command failed: {' '.join(cmd)}")
    return proc.stdout


def resolve_repo_root(repo: str | Path) -> Path:
    """Resolve the top-level Git worktree for ``repo``.

    Allows invoking the tool from a subdirectory or nested submodule checkout;
    all subsequent git calls use the resolved absolute root.

    Args:
        repo: Any path inside the target repository.

    Returns:
        Absolute path to the repository root.
    """
    out = run_git(repo, "rev-parse", "--show-toplevel").strip()
    return Path(out).resolve()


def rev_parse(repo: str | Path, ref: str) -> str:
    """Resolve a ref name to a full object SHA.

    Args:
        repo: Repository root or path inside it.
        ref: Branch, tag, or commit-ish (e.g. ``HEAD``, ``main``).

    Returns:
        40-character commit SHA string.
    """
    return run_git(repo, "rev-parse", ref).strip()


def merge_base(repo: str | Path, base_ref: str, head_ref: str) -> str:
    """Find the best common ancestor of two refs.

    Implements PR-style comparison: diff from ``merge_base`` to ``head_ref``,
    not the entire symmetric difference between branches.

    Args:
        repo: Repository path.
        base_ref: Base branch or ref (e.g. ``main``).
        head_ref: Head branch or ref (e.g. ``feature`` or ``HEAD``).

    Returns:
        Commit SHA of the merge base.
    """
    return run_git(repo, "merge-base", base_ref, head_ref).strip()


def is_binary_file(repo: str | Path, ref: str, path: str) -> bool:
    """Heuristically detect a binary blob at ``ref:path``.

    Uses ``git grep -I`` which skips binary content. Rarely called directly;
    :func:`detect_binary_diff` is preferred for branch comparisons.

    Args:
        repo: Repository path.
        ref: Commit or tree ref prefix for ``ref:path`` syntax.
        path: Repo-relative file path.

    Returns:
        ``True`` when the blob appears binary or unreadable.
    """
    try:
        out = run_git(repo, "grep", "-I", "--text", ".", ref + ":" + path, check=False)
    except GitError:
        return True
    return out.strip() == ""


def show_file_at_ref(repo: str | Path, ref: str, path: str) -> str | None:
    """Return file contents at a specific commit, or ``None`` if missing.

    Used to obtain old/new source text for ctags without checking out branches.

    Args:
        repo: Repository path.
        ref: Commit SHA or ref name.
        path: Repo-relative file path.

    Returns:
        Decoded file text, or ``None`` when the path does not exist at ``ref``.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


@dataclass
class ChangedFile:
    """One entry from ``git diff --name-status`` between two commits.

    Attributes:
        old_path: Path in the base tree; ``None`` for added files.
        new_path: Path in the head tree; ``None`` for deleted files.
        change_type: One of ``add``, ``delete``, ``modify``, ``rename``, ``copy``, ``unknown``.
        is_binary: Reserved; binary detection is done separately via diff text.
    """

    old_path: str | None
    new_path: str | None
    change_type: str
    is_binary: bool = False


def parse_name_status_line(line: str) -> ChangedFile:
    """Parse a single line of ``git diff --name-status`` output.

    Handles rename/copy status codes (``R100``, ``C90``) which include two
    tab-separated paths after the status letter.

    Args:
        line: One line from ``git diff --name-status`` (no trailing newline).

    Returns:
        Populated :class:`ChangedFile` for that line.
    """
    parts = line.split("\t")
    status = parts[0]
    if status.startswith("R") or status.startswith("C"):
        old_path, new_path = parts[1], parts[2]
        change_type = "rename" if status.startswith("R") else "copy"
        return ChangedFile(old_path=old_path, new_path=new_path, change_type=change_type)
    if status == "A":
        return ChangedFile(old_path=None, new_path=parts[1], change_type="add")
    if status == "D":
        return ChangedFile(old_path=parts[1], new_path=None, change_type="delete")
    if status == "M":
        return ChangedFile(old_path=parts[1], new_path=parts[1], change_type="modify")
    if status == "T":
        return ChangedFile(old_path=parts[1], new_path=parts[1], change_type="unknown")
    path = parts[-1]
    return ChangedFile(old_path=path, new_path=path, change_type="unknown")


def list_changed_files(repo: str | Path, from_ref: str, to_ref: str) -> list[ChangedFile]:
    """List files changed between ``from_ref`` and ``to_ref``.

    Uses ``-M`` so renames are detected. Called with ``merge_base`` and
    ``head_commit`` from :func:`semantic_branch_diff.diff_engine.semantic_diff`.

    Args:
        repo: Repository path.
        from_ref: Older commit (typically merge-base SHA).
        to_ref: Newer commit (typically head SHA).

    Returns:
        Ordered list of :class:`ChangedFile` records.
    """
    out = run_git(repo, "diff", "--name-status", "-M", from_ref, to_ref)
    files: list[ChangedFile] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        files.append(parse_name_status_line(line))
    return files


def unified_diff(repo: str | Path, from_ref: str, to_ref: str, path: str | None = None) -> str:
    """Return a zero-context unified diff between two commits.

    ``-U0`` minimizes hunks so :func:`parse_diff_line_numbers` can map each
    ``+``/``-`` line to an absolute line number without context noise.

    Args:
        repo: Repository path.
        from_ref: Base commit.
        to_ref: Head commit.
        path: Optional single-file filter (repo-relative).

    Returns:
        Raw unified diff text.
    """
    args = ["diff", "-U0", from_ref, to_ref]
    if path:
        args.append("--")
        args.append(path)
    return run_git(repo, *args)


def parse_diff_line_numbers(diff_text: str) -> tuple[list[int], list[int]]:
    """Extract added and deleted line numbers from a unified diff.

    Walks hunk headers (``@@``) to track old/new line counters, then records
    line numbers for each insertion and deletion. Used to attribute changes to
    ctags symbol ranges.

    Args:
        diff_text: Output of :func:`unified_diff`.

    Returns:
        Tuple ``(added_lines, deleted_lines)`` — 1-based line indices in the
        new and old file revisions respectively.
    """
    added: list[int] = []
    deleted: list[int] = []
    old_line = 0
    new_line = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            parts = line.split(" ")
            old_part = parts[1]
            new_part = parts[2]
            old_line = int(old_part.split(",")[0].replace("-", "")) - 1
            new_line = int(new_part.split(",")[0].replace("+", "")) - 1
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            old_line += 1
            deleted.append(old_line)
            continue
        if line.startswith("+"):
            new_line += 1
            added.append(new_line)
            continue
        if line.startswith(r"\ "):
            continue
        # Context line: advances both old and new counters.
        old_line += 1
        new_line += 1
    return added, deleted


def detect_binary_diff(repo: str | Path, from_ref: str, to_ref: str, path: str) -> bool:
    """Return whether git reports a binary diff for ``path``.

    Binary files are skipped for ctags analysis in the diff engine.

    Args:
        repo: Repository path.
        from_ref: Base commit.
        to_ref: Head commit.
        path: Repo-relative file path.

    Returns:
        ``True`` when the unified diff contains ``Binary files``.
    """
    diff = unified_diff(repo, from_ref, to_ref, path)
    return "Binary files" in diff


def diff_texts(old_content: str, new_content: str, old_path: str, new_path: str) -> str:
    """Build a zero-context unified diff between two in-memory file versions.

    Used when comparing directory snapshots (``old/`` vs ``new/`` example
    folders) without invoking git.

    Args:
        old_content: Text at the base revision (``""`` when the file is new).
        new_content: Text at the head revision (``""`` when the file is deleted).
        old_path: Label for the ``---`` file line.
        new_path: Label for the ``+++`` file line.

    Returns:
        Unified diff string compatible with :func:`parse_diff_line_numbers`.
    """
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=old_path,
            tofile=new_path,
            lineterm="",
            n=0,
        )
    )


def is_binary_content(content: str) -> bool:
    """Return whether raw content looks binary (NUL byte present).

    Args:
        content: File text or bytes decoded as text.

    Returns:
        ``True`` when a NUL byte is found.
    """
    return "\0" in content
