"""Universal / Exuberant Ctags integration via python-ctags3.

Runs the external ``ctags`` executable on temporary file snapshots and reads
tags through python-ctags3. Produces normalized :class:`~semantic_branch_diff.symbols.Symbol`
lists consumed by the diff engine.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from semantic_branch_diff.symbols import (
    Symbol,
    SymbolKey,
    deduplicate_symbols,
    effective_kind,
    symbol_key_from_tag_fields,
)

logger = logging.getLogger(__name__)

try:
    import ctags as _ctags
except ImportError as exc:  # pragma: no cover - exercised via explicit check
    _ctags = None
    _CTAGS_IMPORT_ERROR = exc
else:
    _CTAGS_IMPORT_ERROR = None


class CtagsError(RuntimeError):
    """Raised when ctags or python-ctags3 is missing or the tags run fails."""


def require_ctags_library() -> None:
    """Verify python-ctags3 is importable before reading tag files.

    Called at the start of tag parsing so users get a clear install hint
    rather than an obscure ``AttributeError``.

    Raises:
        CtagsError: When ``python-ctags3`` is not installed.
    """
    if _ctags is None:
        raise CtagsError("python-ctags3 is required but not installed. Install with: pip install python-ctags3") from _CTAGS_IMPORT_ERROR


def require_ctags_executable(path: str = "ctags") -> str:
    """Resolve and validate the ctags executable path.

    Args:
        path: Binary name or absolute path (from ``--ctags`` CLI flag).

    Returns:
        Resolved executable path from ``shutil.which``.

    Raises:
        CtagsError: When the executable cannot be found on ``PATH``.
    """
    resolved = shutil.which(path)
    if not resolved:
        raise CtagsError(f"ctags executable not found at '{path}'. Install Universal Ctags or set --ctags PATH.")
    return resolved


def _decode_field(entry: object, key: str) -> str:
    """Read one extension field from a python-ctags3 ``TagEntry``.

    TagEntry accepts string keys for standard fields and bytes keys for
    extension fields (``class``, ``namespace``, etc.). Tries both forms.

    Args:
        entry: Mutable tag record from ``CTags.next()``.
        key: Field name (e.g. ``"name"``, ``"class"``).

    Returns:
        Decoded UTF-8 string, or ``""`` when absent.
    """
    candidates: list[str | bytes] = [key]
    if isinstance(key, str):
        candidates.append(key.encode("utf-8"))
    for k in candidates:
        try:
            value = entry[k]  # type: ignore[index]
        except (KeyError, TypeError):
            continue
        if value is None:
            continue
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value)
    return ""


def _ctags_flavor(executable: str) -> str:
    """Detect Universal vs Exuberant ctags from ``--version`` output.

    Args:
        executable: Path to the ctags binary.

    Returns:
        ``"universal"`` or ``"exuberant"``.
    """
    proc = subprocess.run([executable, "--version"], capture_output=True, text=True)
    text = (proc.stdout + proc.stderr).lower()
    if "universal ctags" in text or "ctags-go" in text:
        return "universal"
    return "exuberant"


def _ctags_command(executable: str, tags_file: Path, source_file: Path) -> list[str]:
    """Build a ctags argv list appropriate for the installed flavor.

    Universal builds support ``--extras=+q`` and ``end`` fields; Exuberant
    uses a reduced flag set and relies on brace matching for end lines.

    Args:
        executable: Resolved ctags binary path.
        tags_file: Output tags file path.
        source_file: Temporary source file to tag.

    Returns:
        Argument list suitable for ``subprocess.run``.
    """
    flavor = _ctags_flavor(executable)
    if flavor == "universal":
        return [
            executable,
            "--fields=+neK",
            "--extras=+q",
            "-f",
            str(tags_file),
            str(source_file),
        ]
    return [
        executable,
        "--fields=+nK",
        "-f",
        str(tags_file),
        str(source_file),
    ]


def _infer_end_line(source: str, start_line: int, kind: str) -> int:
    """Estimate symbol end line when ctags omits the ``end`` field.

    For functions/methods, scans forward from ``start_line`` counting brace
    depth until the enclosing block closes.

    Args:
        source: Full file text.
        start_line: 1-based start line from ctags.
        kind: Effective symbol kind from normalization.

    Returns:
        1-based end line (inclusive).
    """
    lines = source.splitlines()
    if start_line < 1 or start_line > len(lines):
        return start_line
    if kind in {"function", "method", "constructor", "destructor"}:
        depth = 0
        started = False
        for idx in range(start_line - 1, len(lines)):
            line = lines[idx]
            for ch in line:
                if ch == "{":
                    depth += 1
                    started = True
                elif ch == "}":
                    depth -= 1
                    if started and depth == 0:
                        return idx + 1
        return len(lines)
    return start_line


def _read_tags_file(tags_path: Path, source_path: str, source_content: str) -> list[Symbol]:
    """Parse a ctags tags file into deduplicated :class:`Symbol` objects.

    Iterates every tag entry, normalizes fields through
    :func:`~semantic_branch_diff.symbols.symbol_key_from_tag_fields`, and
    applies :func:`~semantic_branch_diff.symbols.deduplicate_symbols`.

    Args:
        tags_path: Path to the generated tags file.
        source_path: Original repo-relative path (stored on symbols).
        source_content: Source text (for end-line inference).

    Returns:
        Deduplicated symbol list for one file revision.
    """
    require_ctags_library()
    assert _ctags is not None

    symbols: list[Symbol] = []
    reader = _ctags.CTags(str(tags_path))
    entry = _ctags.TagEntry()
    while reader.next(entry) == _ctags.SUCCESS:
        name = _decode_field(entry, "name")
        if not name or name.startswith("!_"):
            continue
        raw_kind = _decode_field(entry, "kind")
        line_no = int(_decode_field(entry, "lineNumber") or "0")
        end_raw = _decode_field(entry, "end")
        pattern = _decode_field(entry, "pattern")
        scope = _decode_field(entry, "scope")
        class_field = _decode_field(entry, "class")
        namespace_field = _decode_field(entry, "namespace")
        enum_field = _decode_field(entry, "enum")
        interface_field = _decode_field(entry, "interface")
        file_scope_raw = _decode_field(entry, "fileScope")
        file_scope = file_scope_raw in {"1", "true", "True"}

        kind = effective_kind(raw_kind, name, scope, pattern)
        end_line = int(end_raw) if end_raw.isdigit() else _infer_end_line(source_content, line_no, kind)
        if end_line < line_no:
            end_line = line_no

        key, short_name, norm_scope = symbol_key_from_tag_fields(
            name=name,
            raw_kind=raw_kind,
            scope=scope,
            class_field=class_field,
            namespace_field=namespace_field,
            enum_field=enum_field,
            interface_field=interface_field,
            pattern=pattern,
            _file_scope=file_scope,
        )
        symbols.append(
            Symbol(
                key=key,
                name=short_name,
                qualified_name=key.qualified_name,
                kind=key.kind,
                raw_kind=raw_kind,
                scope=norm_scope,
                path=source_path,
                start_line=line_no,
                end_line=end_line,
                file_scope=file_scope,
                pattern=pattern or None,
                signature=key.signature,
            )
        )
    return deduplicate_symbols(symbols)


def generate_symbols(
    *,
    source_content: str,
    source_path: str,
    ctags_executable: str,
    tmp_dir: Path | None = None,
) -> list[Symbol]:
    """Run ctags on in-memory source and return normalized symbols.

    Primary entry used by :func:`~semantic_branch_diff.diff_engine.analyze_file_diff`
    for both old and new file revisions. Writes to a temp file (never into the
    repo), invokes ctags, parses tags, and cleans up.

    Args:
        source_content: Full text of one file revision.
        source_path: Repo-relative path (determines ``.cpp`` vs ``.h`` suffix).
        ctags_executable: Binary name or path for ctags.
        tmp_dir: Optional shared temp directory; created when ``None``.

    Returns:
        Symbol list, or ``[]`` for empty content / missing tags file.

    Raises:
        CtagsError: When ctags executable or library is missing, or ctags fails.
    """
    if not source_content:
        return []

    executable = require_ctags_executable(ctags_executable)
    suffix = Path(source_path).suffix or ".cpp"
    own_tmp = tmp_dir is None
    if own_tmp:
        tmp_dir = Path(tempfile.mkdtemp(prefix="semantic_branch_diff_"))
    assert tmp_dir is not None

    source_file = tmp_dir / f"source{suffix}"
    tags_file = tmp_dir / "tags"
    try:
        # Write snapshot with correct extension so ctags picks the C++ parser.
        source_file.write_text(source_content, encoding="utf-8")
        cmd = _ctags_command(executable, tags_file, source_file)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise CtagsError(stderr or f"ctags failed: {' '.join(cmd)}")
        if not tags_file.exists():
            return []
        return _read_tags_file(tags_file, source_path, source_content)
    finally:
        if own_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def symbols_by_key(symbols: list[Symbol]) -> dict[SymbolKey, Symbol]:
    """Index symbols by their normalized :class:`SymbolKey` for set comparisons.

    Used to compute added/removed/common symbol keys between two revisions.

    Args:
        symbols: List from :func:`generate_symbols`.

    Returns:
        Dict mapping each key to its symbol (last wins on duplicate keys).
    """
    out: dict[SymbolKey, Symbol] = {}
    for sym in symbols:
        out[sym.key] = sym
    return out
