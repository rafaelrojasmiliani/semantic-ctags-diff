"""Run ctags and read tags files into normalized :class:`FileIndex` objects."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ctags3_improved._raw_tag import _RawTag, _symbol_from_raw
from ctags3_improved.model import FileIndex, Symbol
from ctags3_improved.normalize import effective_kind
from ctags3_improved.query import deduplicate_symbols, symbols_by_key

logger = logging.getLogger(__name__)

try:
    import ctags as _ctags
except ImportError as exc:  # pragma: no cover
    _ctags = None
    _CTAGS_IMPORT_ERROR = exc
else:
    _CTAGS_IMPORT_ERROR = None


class CtagsError(RuntimeError):
    """Raised when ctags or python-ctags3 is missing or the tags run fails."""


def require_ctags_library() -> None:
    """Verify python-ctags3 is importable before reading tag files."""
    if _ctags is None:
        raise CtagsError(
            "python-ctags3 is required but not installed. Install with: pip install python-ctags3"
        ) from _CTAGS_IMPORT_ERROR


def require_ctags_executable(path: str = "ctags") -> str:
    """Resolve and validate the ctags executable path."""
    resolved = shutil.which(path)
    if not resolved:
        raise CtagsError(
            f"ctags executable not found at '{path}'. Install Universal Ctags or set --ctags PATH."
        )
    return resolved


def _decode_field(entry: object, key: str) -> str:
    """Read one extension field from a python-ctags3 ``TagEntry``."""
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
    """Detect Universal vs Exuberant ctags from ``--version`` output."""
    proc = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (proc.stdout + proc.stderr).lower()
    if "universal ctags" in text or "ctags-go" in text:
        return "universal"
    return "exuberant"


def _ctags_command(executable: str, tags_file: Path, source_file: Path) -> list[str]:
    """Build a ctags argv list appropriate for the installed flavor."""
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
    """Estimate symbol end line when ctags omits the ``end`` field."""
    lines = source.splitlines()
    if start_line < 1 or start_line > len(lines):
        return start_line
    if kind in {"function", "method", "constructor", "destructor"}:
        depth = 0
        started = False
        for idx in range(start_line - 1, len(lines)):
            line = lines[idx]
            for char in line:
                if char == "{":
                    depth += 1
                    started = True
                elif char == "}":
                    depth -= 1
                    if started and depth == 0:
                        return idx + 1
        return len(lines)
    return start_line


def _read_tags_file(tags_path: Path, source_path: str, source_content: str) -> list[Symbol]:
    """Parse a ctags tags file into deduplicated :class:`Symbol` objects."""
    require_ctags_library()
    assert _ctags is not None

    symbols: list[Symbol] = []
    reader = _ctags.CTags(str(tags_path))
    entry = _ctags.TagEntry()
    while reader.next(entry) == _ctags.SUCCESS:
        name = _decode_field(entry, "name")
        if not name or name.startswith("!_"):
            continue
        tag = _RawTag(
            name=name,
            raw_kind=_decode_field(entry, "kind"),
            scope=_decode_field(entry, "scope"),
            class_field=(
                _decode_field(entry, "class")
                or _decode_field(entry, "struct")
                or _decode_field(entry, "union")
            ),
            namespace_field=_decode_field(entry, "namespace"),
            enum_field=_decode_field(entry, "enum"),
            interface_field=_decode_field(entry, "interface"),
            pattern=_decode_field(entry, "pattern"),
            line=int(_decode_field(entry, "lineNumber") or "0"),
            end_raw=_decode_field(entry, "end"),
            file_scope=_decode_field(entry, "fileScope") in {"1", "true", "True"},
        )
        kind = effective_kind(tag.raw_kind, tag.name, tag.scope, tag.pattern)
        end_line = (
            int(tag.end_raw)
            if tag.end_raw.isdigit()
            else _infer_end_line(source_content, tag.line, kind)
        )
        symbols.append(_symbol_from_raw(tag, path=source_path, end_line=end_line))
    return deduplicate_symbols(symbols)


def generate_symbols(
    *,
    source_content: str,
    source_path: str,
    ctags_executable: str = "ctags",
    tmp_dir: Path | None = None,
) -> list[Symbol]:
    """Run ctags on in-memory source and return a flat normalized symbol list."""
    return index_source(
        source_content=source_content,
        source_path=source_path,
        ctags_executable=ctags_executable,
        tmp_dir=tmp_dir,
    ).symbols


def index_source(
    *,
    source_content: str,
    source_path: str,
    ctags_executable: str = "ctags",
    tmp_dir: Path | None = None,
) -> FileIndex:
    """Run ctags on in-memory source and return a :class:`FileIndex`.

    Primary entry point for this package. Writes a temp file (never into the
    caller's tree), invokes ctags, and returns a flat :class:`FileIndex`.
    """
    if not source_content:
        return FileIndex(path=source_path, symbols=[])

    executable = require_ctags_executable(ctags_executable)
    suffix = Path(source_path).suffix or ".cpp"
    own_tmp = tmp_dir is None
    if own_tmp:
        tmp_dir = Path(tempfile.mkdtemp(prefix="ctags3_improved_"))
    assert tmp_dir is not None

    source_file = tmp_dir / f"source{suffix}"
    tags_file = tmp_dir / "tags"
    try:
        source_file.write_text(source_content, encoding="utf-8")
        cmd = _ctags_command(executable, tags_file, source_file)
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise CtagsError(stderr or f"ctags failed: {' '.join(cmd)}")
        if not tags_file.exists():
            return FileIndex(path=source_path, symbols=[])
        symbols = _read_tags_file(tags_file, source_path, source_content)
        return FileIndex(path=source_path, symbols=symbols)
    finally:
        if own_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# Re-export for callers that only need the adapter surface.
__all__ = [
    "CtagsError",
    "FileIndex",
    "Symbol",
    "generate_symbols",
    "index_source",
    "require_ctags_executable",
    "require_ctags_library",
    "symbols_by_key",
]
