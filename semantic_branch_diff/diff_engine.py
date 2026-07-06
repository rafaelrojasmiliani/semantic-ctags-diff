"""Core semantic diff engine.

Orchestrates Git change discovery, ctags symbol extraction, and classification
of added/removed/modified symbols plus file-scope line changes. Public entry:
:func:`semantic_diff`.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from semantic_branch_diff import git_utils
from semantic_branch_diff.ctags_adapter import generate_symbols, symbols_by_key
from semantic_branch_diff.pydriller_adapter import enrich_modified_symbol
from semantic_branch_diff.symbols import (
    Symbol,
    best_enclosing_symbol,
)

logger = logging.getLogger(__name__)

DEFAULT_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")

EXTENSION_LANGUAGE = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "c",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
}


@dataclass
class ModifiedSymbolResult:
    """A symbol present in both revisions whose body or signature changed.

    Attributes:
        kind: Normalized symbol kind.
        qualified_name: Full C++ name for reports.
        name: Short name segment.
        scope: Parent scope string.
        file: Repo-relative path.
        old_range: ``[start, end]`` line range at merge-base.
        new_range: ``[start, end]`` line range at head.
        changed_old_lines: Deleted lines intersecting ``old_range``.
        changed_new_lines: Added lines intersecting ``new_range``.
        classification: Always ``"modified"`` for this type.
        pydriller: Optional Lizard metrics from enrichment.
    """

    kind: str
    qualified_name: str
    name: str
    scope: str
    file: str
    old_range: list[int]
    new_range: list[int]
    changed_old_lines: list[int]
    changed_new_lines: list[int]
    classification: str = "modified"
    pydriller: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict, omitting empty ``pydriller``."""
        data = asdict(self)
        if not data["pydriller"]:
            del data["pydriller"]
        return data


@dataclass
class SymbolSummary:
    """Compact symbol record for added or removed classifications.

    Attributes:
        kind: Normalized symbol kind.
        qualified_name: Full name.
        name: Short name.
        scope: Parent scope.
        file: Repo-relative path.
        range: ``[start_line, end_line]`` in the relevant revision.
        classification: ``"added"`` or ``"removed"``.
    """

    kind: str
    qualified_name: str
    name: str
    scope: str
    file: str
    range: list[int]
    classification: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)


@dataclass
class FileScopeChanges:
    """Line-level changes not attributed to any ctags symbol (e.g. includes).

    Attributes:
        added_lines: New-file line numbers outside symbol ranges.
        deleted_lines: Old-file line numbers outside symbol ranges.
    """

    added_lines: list[int] = field(default_factory=list)
    deleted_lines: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, int | list[int]]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)


@dataclass
class FileDiffResult:
    """Semantic diff outcome for a single changed file.

    Attributes:
        path: Display path (new path, or old for deletions).
        old_path: Path at merge-base.
        change_type: Git change type string.
        language: Inferred language from extension.
        added_lines: All added line numbers from unified diff.
        deleted_lines: All deleted line numbers from unified diff.
        added_symbols: Symbols only in head inventory.
        removed_symbols: Symbols only in base inventory.
        modified_symbols: Symbols in both with intersecting changes.
        file_scope_changes: Non-symbol line changes.
        skipped: True when file was not analyzed.
        skip_reason: Reason when skipped (``binary``, ``extension_not_included``).
    """

    path: str
    old_path: str
    change_type: str
    language: str
    added_lines: list[int]
    deleted_lines: list[int]
    added_symbols: list[SymbolSummary]
    removed_symbols: list[SymbolSummary]
    modified_symbols: list[ModifiedSymbolResult]
    file_scope_changes: FileScopeChanges
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the stable JSON schema used by the CLI."""
        return {
            "path": self.path,
            "old_path": self.old_path,
            "change_type": self.change_type,
            "language": self.language,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "added_symbols": [s.to_dict() for s in self.added_symbols],
            "removed_symbols": [s.to_dict() for s in self.removed_symbols],
            "modified_symbols": [s.to_dict() for s in self.modified_symbols],
            "file_scope_changes": self.file_scope_changes.to_dict(),
            **({"skipped": True, "skip_reason": self.skip_reason} if self.skipped else {}),
        }


@dataclass
class SemanticDiffResult:
    """Top-level result for a branch comparison.

    Attributes:
        repo: Absolute repository root path.
        base_ref: Base ref string passed by caller.
        head_ref: Head ref string passed by caller.
        merge_base: Resolved merge-base SHA.
        head_commit: Resolved head SHA.
        files: Per-file diff results.
        summary: Aggregate counts for reporting.
    """

    repo: str
    base_ref: str
    head_ref: str
    merge_base: str
    head_commit: str
    files: list[FileDiffResult]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full result tree for JSON output."""
        return {
            "repo": self.repo,
            "base_ref": self.base_ref,
            "head_ref": self.head_ref,
            "merge_base": self.merge_base,
            "head_commit": self.head_commit,
            "files": [f.to_dict() for f in self.files],
            "summary": self.summary,
        }


def _extension_allowed(path: str, extensions: tuple[str, ...]) -> bool:
    """Check whether a file suffix is in the configured analyze list.

    Args:
        path: Repo-relative file path.
        extensions: Allowed suffixes from ``--include`` / API.

    Returns:
        ``True`` when the path suffix (lowercased) is allowed.
    """
    return Path(path).suffix.lower() in extensions


def _language_for(path: str) -> str:
    """Map file extension to a language label for JSON output.

    Args:
        path: Repo-relative file path.

    Returns:
        Language string (``cpp``, ``c``, or ``unknown``).
    """
    return EXTENSION_LANGUAGE.get(Path(path).suffix.lower(), "unknown")


def _symbol_summary(sym: Symbol, file_path: str, classification: str) -> SymbolSummary:
    """Build a :class:`SymbolSummary` from a :class:`Symbol` for add/remove lists.

    Args:
        sym: Symbol from old or new inventory.
        file_path: Repo-relative path for reports.
        classification: ``"added"`` or ``"removed"``.

    Returns:
        Summary record for JSON/Markdown renderers.
    """
    start, end = sym.start_line, sym.end_line
    return SymbolSummary(
        kind=sym.kind,
        qualified_name=sym.qualified_name,
        name=sym.name,
        scope=sym.scope,
        file=file_path,
        range=[start, end],
        classification=classification,
    )


def _lines_in_range(lines: list[int], start: int, end: int) -> list[int]:
    """Filter changed line numbers to those inside a symbol range.

    Args:
        lines: Added or deleted line numbers from unified diff.
        start: Symbol start line (inclusive).
        end: Symbol end line (inclusive).

    Returns:
        Sorted unique line numbers within ``[start, end]``.
    """
    return sorted({ln for ln in lines if start <= ln <= end})


def _signature_changed(old_sym: Symbol, new_sym: Symbol) -> bool:
    """Detect meaningful signature/pattern change between two symbol revisions.

    Treats a symbol as modified even when line numbers are unchanged but the
    ctags pattern (declaration shape) differs.

    Args:
        old_sym: Symbol at merge-base.
        new_sym: Symbol at head.

    Returns:
        ``True`` when pattern or signature fields differ.
    """
    if old_sym.pattern and new_sym.pattern and old_sym.pattern != new_sym.pattern:
        return True
    return bool(old_sym.signature and new_sym.signature and old_sym.signature != new_sym.signature)


def _collect_tree_files(root: Path, extensions: tuple[str, ...]) -> dict[str, Path]:
    """Map repo-relative paths to files under ``root`` matching ``extensions``.

    Args:
        root: Directory to scan recursively.
        extensions: Allowed suffixes (e.g. ``.cpp``, ``.h``).

    Returns:
        Dict of relative POSIX path -> absolute :class:`Path`.
    """
    found: dict[str, Path] = {}
    if not root.is_dir():
        return found
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            found[path.relative_to(root).as_posix()] = path
    return found


def _infer_change_type(old_exists: bool, new_exists: bool) -> str:
    """Map file presence on each side to a Git-like change type string."""
    if old_exists and new_exists:
        return "modify"
    if new_exists:
        return "add"
    if old_exists:
        return "delete"
    return "unknown"


def analyze_file_pair(
    *,
    display_path: str,
    old_path: str,
    new_path: str,
    change_type: str,
    old_content: str,
    new_content: str,
    added_lines: list[int],
    deleted_lines: list[int],
    ctags_executable: str,
    extensions: tuple[str, ...],
    use_pydriller_methods: bool,
    tmp_dir: Path,
    repo_path: str = "",
) -> FileDiffResult:
    """Compute semantic symbol diff for one file from in-memory old/new content.

    Core per-file pipeline shared by Git mode and directory snapshot mode.
    Runs ctags on both sides, classifies symbols, and attributes line changes.

    Args:
        display_path: Path shown in reports (usually the new or sole path).
        old_path: Old-side path label for ctags.
        new_path: New-side path label for ctags.
        change_type: ``add``, ``delete``, ``modify``, etc.
        old_content: Base revision text (empty when added).
        new_content: Head revision text (empty when deleted).
        added_lines: 1-based added line numbers in the new file.
        deleted_lines: 1-based deleted line numbers in the old file.
        ctags_executable: Ctags binary path.
        extensions: Allowed suffixes (for skip check).
        use_pydriller_methods: Whether to attach Lizard metrics.
        tmp_dir: Shared temp directory for ctags runs.
        repo_path: Optional repo path for PyDriller enrichment metadata.

    Returns:
        :class:`FileDiffResult` with symbol and file-scope classifications.
    """
    if not _extension_allowed(display_path, extensions):
        return FileDiffResult(
            path=display_path,
            old_path=old_path,
            change_type=change_type,
            language=_language_for(display_path),
            added_lines=[],
            deleted_lines=[],
            added_symbols=[],
            removed_symbols=[],
            modified_symbols=[],
            file_scope_changes=FileScopeChanges(),
            skipped=True,
            skip_reason="extension_not_included",
        )

    if git_utils.is_binary_content(old_content) or git_utils.is_binary_content(new_content):
        return FileDiffResult(
            path=display_path,
            old_path=old_path,
            change_type=change_type,
            language=_language_for(display_path),
            added_lines=[],
            deleted_lines=[],
            added_symbols=[],
            removed_symbols=[],
            modified_symbols=[],
            file_scope_changes=FileScopeChanges(),
            skipped=True,
            skip_reason="binary",
        )

    old_symbols = generate_symbols(
        source_content=old_content,
        source_path=old_path,
        ctags_executable=ctags_executable,
        tmp_dir=tmp_dir,
    )
    new_symbols = generate_symbols(
        source_content=new_content,
        source_path=new_path,
        ctags_executable=ctags_executable,
        tmp_dir=tmp_dir,
    )

    old_by_key = symbols_by_key(old_symbols)
    new_by_key = symbols_by_key(new_symbols)
    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    added_symbols = [_symbol_summary(new_by_key[k], display_path, "added") for k in sorted(added_keys, key=lambda x: x.qualified_name)]
    removed_symbols = [
        _symbol_summary(old_by_key[k], display_path, "removed") for k in sorted(removed_keys, key=lambda x: x.qualified_name)
    ]

    modified_symbols: list[ModifiedSymbolResult] = []

    for line in added_lines:
        sym = best_enclosing_symbol(new_symbols, line)
        if sym is None or sym.key in added_keys:
            continue

    for line in deleted_lines:
        sym = best_enclosing_symbol(old_symbols, line)
        if sym is None or sym.key in removed_keys:
            continue

    for key in sorted(common_keys, key=lambda x: x.qualified_name):
        old_sym = old_by_key[key]
        new_sym = new_by_key[key]
        changed_old = _lines_in_range(deleted_lines, old_sym.start_line, old_sym.end_line)
        changed_new = _lines_in_range(added_lines, new_sym.start_line, new_sym.end_line)
        if not changed_old and not changed_new and not _signature_changed(old_sym, new_sym):
            continue
        py_meta = enrich_modified_symbol(
            _repo_path=repo_path,
            old_content=old_content,
            new_content=new_content,
            file_path=display_path,
            qualified_name=new_sym.qualified_name,
            enabled=use_pydriller_methods,
        )
        modified_symbols.append(
            ModifiedSymbolResult(
                kind=new_sym.kind,
                qualified_name=new_sym.qualified_name,
                name=new_sym.name,
                scope=new_sym.scope,
                file=display_path,
                old_range=[old_sym.start_line, old_sym.end_line],
                new_range=[new_sym.start_line, new_sym.end_line],
                changed_old_lines=changed_old,
                changed_new_lines=changed_new,
                pydriller=py_meta,
            )
        )

    modified_old_ranges = {tuple(m.old_range) for m in modified_symbols}
    modified_new_ranges = {tuple(m.new_range) for m in modified_symbols}

    def _line_in_modified_ranges(line: int, ranges: set[tuple[int, int]], symbols: list[Symbol]) -> bool:
        sym = best_enclosing_symbol(symbols, line)
        if sym and sym.key in common_keys:
            return True
        return any(start <= line <= end for start, end in ranges)

    file_scope_added = sorted(
        ln
        for ln in added_lines
        if not _line_in_modified_ranges(ln, modified_new_ranges, new_symbols) and best_enclosing_symbol(new_symbols, ln) is None
    )
    file_scope_deleted = sorted(
        ln
        for ln in deleted_lines
        if not _line_in_modified_ranges(ln, modified_old_ranges, old_symbols) and best_enclosing_symbol(old_symbols, ln) is None
    )

    return FileDiffResult(
        path=display_path,
        old_path=old_path,
        change_type=change_type,
        language=_language_for(display_path),
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        added_symbols=added_symbols,
        removed_symbols=removed_symbols,
        modified_symbols=modified_symbols,
        file_scope_changes=FileScopeChanges(
            added_lines=file_scope_added,
            deleted_lines=file_scope_deleted,
        ),
    )


def analyze_file_diff(
    *,
    repo: Path,
    merge_base: str,
    head_commit: str,
    changed: git_utils.ChangedFile,
    ctags_executable: str,
    extensions: tuple[str, ...],
    use_pydriller_methods: bool,
    tmp_dir: Path,
) -> FileDiffResult:
    """Compute semantic symbol diff for one changed file.

    Pipeline per file: filter extension -> skip binary -> load old/new content
    -> parse line diff -> run ctags on both sides -> classify symbols.

    Args:
        repo: Absolute repository root.
        merge_base: Base commit SHA.
        head_commit: Head commit SHA.
        changed: File metadata from ``git diff --name-status``.
        ctags_executable: Path to ctags binary.
        extensions: Allowed file suffixes.
        use_pydriller_methods: Whether to attach Lizard metrics.
        tmp_dir: Shared temp directory for ctags runs.

    Returns:
        :class:`FileDiffResult` with symbols and file-scope changes.
    """
    display_path = changed.new_path or changed.old_path or ""
    old_path = changed.old_path or display_path
    new_path = changed.new_path or display_path

    if not _extension_allowed(display_path, extensions):
        return FileDiffResult(
            path=display_path,
            old_path=old_path,
            change_type=changed.change_type,
            language=_language_for(display_path),
            added_lines=[],
            deleted_lines=[],
            added_symbols=[],
            removed_symbols=[],
            modified_symbols=[],
            file_scope_changes=FileScopeChanges(),
            skipped=True,
            skip_reason="extension_not_included",
        )

    if git_utils.detect_binary_diff(repo, merge_base, head_commit, display_path):
        return FileDiffResult(
            path=display_path,
            old_path=old_path,
            change_type=changed.change_type,
            language=_language_for(display_path),
            added_lines=[],
            deleted_lines=[],
            added_symbols=[],
            removed_symbols=[],
            modified_symbols=[],
            file_scope_changes=FileScopeChanges(),
            skipped=True,
            skip_reason="binary",
        )

    old_content = git_utils.show_file_at_ref(repo, merge_base, old_path) if changed.change_type != "add" and old_path else ""
    new_content = git_utils.show_file_at_ref(repo, head_commit, new_path) if changed.change_type != "delete" and new_path else ""

    diff_path = new_path if changed.change_type != "delete" else old_path
    diff_text = git_utils.unified_diff(repo, merge_base, head_commit, diff_path or None)
    added_lines, deleted_lines = git_utils.parse_diff_line_numbers(diff_text)

    return analyze_file_pair(
        display_path=display_path,
        old_path=old_path,
        new_path=new_path,
        change_type=changed.change_type,
        old_content=old_content or "",
        new_content=new_content or "",
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        ctags_executable=ctags_executable,
        extensions=extensions,
        use_pydriller_methods=use_pydriller_methods,
        tmp_dir=tmp_dir,
        repo_path=str(repo),
    )


def _build_summary(file_results: list[FileDiffResult]) -> dict[str, int]:
    """Aggregate symbol counts across all per-file results."""
    return {
        "files_changed": len(file_results),
        "symbols_added": sum(len(f.added_symbols) for f in file_results),
        "symbols_removed": sum(len(f.removed_symbols) for f in file_results),
        "symbols_modified": sum(len(f.modified_symbols) for f in file_results),
    }


def semantic_diff_directories(
    old_dir: str | Path,
    new_dir: str | Path,
    *,
    ctags_executable: str = "ctags",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    use_pydriller_methods: bool = True,
) -> SemanticDiffResult:
    """Compare two directory trees (``old/`` and ``new/``) without Git.

    Intended for examples, tests, and local before/after snapshots. Each
    relative path present in either tree is treated as one changed file.

    Args:
        old_dir: Directory containing the base revision (e.g. ``examples/.../old``).
        new_dir: Directory containing the head revision (e.g. ``examples/.../new``).
        ctags_executable: Ctags binary path.
        extensions: File suffixes to analyze.
        use_pydriller_methods: Whether to attach Lizard metrics.

    Returns:
        :class:`SemanticDiffResult` with synthetic ref labels ``old`` / ``new``.
    """
    old_root = Path(old_dir).resolve()
    new_root = Path(new_dir).resolve()
    old_files = _collect_tree_files(old_root, extensions)
    new_files = _collect_tree_files(new_root, extensions)
    all_paths = sorted(set(old_files) | set(new_files))

    file_results: list[FileDiffResult] = []
    with tempfile.TemporaryDirectory(prefix="semantic_branch_diff_") as tmp:
        tmp_dir = Path(tmp)
        for rel_path in all_paths:
            old_exists = rel_path in old_files
            new_exists = rel_path in new_files
            change_type = _infer_change_type(old_exists, new_exists)
            old_content = old_files[rel_path].read_text(encoding="utf-8") if old_exists else ""
            new_content = new_files[rel_path].read_text(encoding="utf-8") if new_exists else ""
            diff_text = git_utils.diff_texts(old_content, new_content, rel_path, rel_path)
            added_lines, deleted_lines = git_utils.parse_diff_line_numbers(diff_text)
            file_results.append(
                analyze_file_pair(
                    display_path=rel_path,
                    old_path=rel_path,
                    new_path=rel_path,
                    change_type=change_type,
                    old_content=old_content,
                    new_content=new_content,
                    added_lines=added_lines,
                    deleted_lines=deleted_lines,
                    ctags_executable=ctags_executable,
                    extensions=extensions,
                    use_pydriller_methods=use_pydriller_methods,
                    tmp_dir=tmp_dir,
                    repo_path=str(new_root),
                )
            )

    return SemanticDiffResult(
        repo=str(new_root),
        base_ref="old",
        head_ref="new",
        merge_base="old",
        head_commit="new",
        files=file_results,
        summary=_build_summary(file_results),
    )


def _semantic_diff_commits(
    *,
    repo_root: Path,
    from_commit: str,
    to_commit: str,
    base_label: str,
    head_label: str,
    ctags_executable: str,
    extensions: tuple[str, ...],
    use_pydriller_methods: bool,
) -> SemanticDiffResult:
    """Compare two resolved commits inside a repository."""
    changed_files = git_utils.list_changed_files(repo_root, from_commit, to_commit)
    file_results: list[FileDiffResult] = []

    with tempfile.TemporaryDirectory(prefix="semantic_branch_diff_") as tmp:
        tmp_dir = Path(tmp)
        for changed in changed_files:
            path = changed.new_path or changed.old_path
            if not path:
                continue
            logger.debug("analyzing %s (%s)", path, changed.change_type)
            file_results.append(
                analyze_file_diff(
                    repo=repo_root,
                    merge_base=from_commit,
                    head_commit=to_commit,
                    changed=changed,
                    ctags_executable=ctags_executable,
                    extensions=extensions,
                    use_pydriller_methods=use_pydriller_methods,
                    tmp_dir=tmp_dir,
                )
            )

    return SemanticDiffResult(
        repo=str(repo_root),
        base_ref=base_label,
        head_ref=head_label,
        merge_base=from_commit,
        head_commit=to_commit,
        files=file_results,
        summary=_build_summary(file_results),
    )


def semantic_diff(
    *,
    repo: str | None = None,
    base: str = "main",
    head: str = "HEAD",
    from_ref: str | None = None,
    to_ref: str | None = None,
    use_merge_base: bool = True,
    old_dir: str | Path | None = None,
    new_dir: str | Path | None = None,
    ctags_executable: str = "ctags",
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    use_pydriller_methods: bool = True,
    debug: bool = False,
    with_difftastic: bool = False,
) -> SemanticDiffResult:
    """Compare two revisions and return a ctags-based semantic diff.

    Supports three modes:

    1. **Directory snapshots** — pass ``old_dir`` and ``new_dir`` (no Git).
    2. **Commit-to-commit** — pass ``repo``, ``from_ref``, and ``to_ref``.
    3. **Branch / MR** — pass ``repo``, ``base``, and ``head`` (uses merge-base
       when ``use_merge_base=True``, the default).

    Args:
        repo: Git repository path (required for Git modes).
        base: Base branch for MR-style comparison.
        head: Head branch for MR-style comparison.
        from_ref: Explicit older commit/branch (disables merge-base when paired).
        to_ref: Explicit newer commit/branch.
        use_merge_base: When ``True`` with ``base``/``head``, diff ``merge-base..head``.
        old_dir: Base directory tree for snapshot mode.
        new_dir: Head directory tree for snapshot mode.
        ctags_executable: Ctags binary path.
        extensions: File suffixes to analyze.
        use_pydriller_methods: Enable Lizard enrichment on modified symbols.
        debug: Enable debug logging when ``True``.
        with_difftastic: Placeholder for future structural diff hook.

    Returns:
        :class:`SemanticDiffResult` with per-file symbol changes and summary counts.

    Raises:
        ValueError: When required arguments for the selected mode are missing.
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)

    if with_difftastic:
        logger.debug("difftastic hook requested but not yet implemented")

    if old_dir is not None or new_dir is not None:
        if old_dir is None or new_dir is None:
            raise ValueError("both old_dir and new_dir are required for directory comparison")
        return semantic_diff_directories(
            old_dir,
            new_dir,
            ctags_executable=ctags_executable,
            extensions=extensions,
            use_pydriller_methods=use_pydriller_methods,
        )

    if repo is None:
        raise ValueError("repo is required for Git-based comparison")

    repo_root = git_utils.resolve_repo_root(repo)

    if from_ref is not None or to_ref is not None:
        if from_ref is None or to_ref is None:
            raise ValueError("both from_ref and to_ref are required")
        from_commit = git_utils.rev_parse(repo_root, from_ref)
        to_commit = git_utils.rev_parse(repo_root, to_ref)
        return _semantic_diff_commits(
            repo_root=repo_root,
            from_commit=from_commit,
            to_commit=to_commit,
            base_label=from_ref,
            head_label=to_ref,
            ctags_executable=ctags_executable,
            extensions=extensions,
            use_pydriller_methods=use_pydriller_methods,
        )

    if use_merge_base:
        from_commit = git_utils.merge_base(repo_root, base, head)
        to_commit = git_utils.rev_parse(repo_root, head)
    else:
        from_commit = git_utils.rev_parse(repo_root, base)
        to_commit = git_utils.rev_parse(repo_root, head)

    return _semantic_diff_commits(
        repo_root=repo_root,
        from_commit=from_commit,
        to_commit=to_commit,
        base_label=base,
        head_label=head,
        ctags_executable=ctags_executable,
        extensions=extensions,
        use_pydriller_methods=use_pydriller_methods,
    )
