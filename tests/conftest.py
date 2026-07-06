"""Shared helpers for Git-based integration tests.

Provides minimal git workflow utilities to build temporary repositories with
base and feature branches for exercising :func:`semantic_branch_diff.semantic_diff`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> str:
    """Run a subprocess in ``cwd`` and return stdout.

    Args:
        cmd: Argument vector (e.g. ``["git", "commit", ...]``).
        cwd: Working directory for the command.

    Returns:
        Captured stdout text.

    Raises:
        subprocess.CalledProcessError: On non-zero exit.
    """
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout


def init_repo(path: Path) -> None:
    """Create a new Git repository with test user identity configured.

    Args:
        path: Directory that will become the repository root.
    """
    path.mkdir(parents=True, exist_ok=True)
    run(["git", "init"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "config", "user.name", "Test User"], path)


def write_file(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent directories as needed.

    Args:
        path: Destination file path inside the test repo.
        content: File body.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit_all(repo: Path, message: str) -> None:
    """Stage all changes and create a commit.

    Args:
        repo: Repository root.
        message: Commit message string.
    """
    run(["git", "add", "-A"], repo)
    run(["git", "commit", "-m", message], repo)


def create_branch(repo: Path, name: str) -> None:
    """Create and checkout a new branch.

    Args:
        repo: Repository root.
        name: Branch name (e.g. ``feature``).
    """
    run(["git", "checkout", "-b", name], repo)


def checkout(repo: Path, ref: str) -> None:
    """Checkout an existing branch or ref.

    Args:
        repo: Repository root.
        ref: Branch name or commit ref.
    """
    run(["git", "checkout", ref], repo)
