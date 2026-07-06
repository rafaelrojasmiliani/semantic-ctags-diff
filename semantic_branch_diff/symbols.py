"""Symbol normalization and line-to-symbol matching.

Defines the symbol model (keys, ranges, qualified C++ names) and algorithms
to deduplicate ctags output, infer kinds from imperfect tags, and map diff
line numbers to the innermost enclosing symbol.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Lower number = higher priority when a changed line matches overlapping symbols.
KIND_PRIORITY: dict[str, int] = {
    "function": 0,
    "method": 0,
    "constructor": 0,
    "destructor": 0,
    "member": 1,
    "class": 2,
    "struct": 2,
    "interface": 2,
    "enum": 3,
    "union": 3,
    "typedef": 4,
    "namespace": 5,
    "module": 5,
    "package": 5,
    "variable": 6,
    "macro": 7,
    "file": 8,
}

FUNCTION_KINDS = frozenset({"function", "method", "constructor", "destructor", "member"})
CLASS_KINDS = frozenset({"class", "struct", "interface"})


@dataclass(frozen=True)
class SymbolKey:
    """Stable identity for comparing symbols across file revisions.

    Two symbols with the same key in old and new inventories are treated as
    the same logical entity (possibly modified), not added/removed.

    Attributes:
        kind: Normalized kind string (``function``, ``class``, etc.).
        qualified_name: Fully qualified C++ name when available.
        signature: Optional ctags pattern used to detect signature changes.
    """

    kind: str
    qualified_name: str
    signature: str | None = None


@dataclass
class Symbol:
    """One ctags tag after normalization, with source range and metadata.

    Attributes:
        key: Identity used for added/removed/modified classification.
        name: Short unqualified name (last ``::`` segment).
        qualified_name: Full name used in reports.
        kind: Normalized kind (may differ from ``raw_kind``).
        raw_kind: Kind string straight from ctags.
        scope: Enclosing scope string from normalization.
        path: Repo-relative file path.
        start_line: 1-based start line (inclusive).
        end_line: 1-based end line (inclusive).
        file_scope: True for file-level namespace tags.
        pattern: Original ctags search pattern.
        signature: Alias of pattern when used as signature fingerprint.
    """

    key: SymbolKey
    name: str
    qualified_name: str
    kind: str
    raw_kind: str
    scope: str
    path: str
    start_line: int
    end_line: int
    file_scope: bool = False
    pattern: str | None = None
    signature: str | None = None

    def range_size(self) -> int:
        """Return inclusive line span length for overlap comparisons.

        Used when choosing the smallest enclosing symbol for a changed line.

        Returns:
            Number of lines in ``[start_line, end_line]``, minimum 0.
        """
        return max(0, self.end_line - self.start_line + 1)

    def contains_line(self, line: int) -> bool:
        """Check whether ``line`` falls inside this symbol's range.

        Args:
            line: 1-based line number in the file revision being analyzed.

        Returns:
            ``True`` when ``start_line <= line <= end_line``.
        """
        return self.start_line <= line <= self.end_line


def effective_kind(raw_kind: str, name: str, scope: str, pattern: str) -> str:
    """Infer a normalized symbol kind when ctags emits an empty or terse kind.

    Universal and Exuberant ctags sometimes leave ``kind`` blank for out-of-class
    C++ method definitions. This function uses pattern and scope heuristics.

    Args:
        raw_kind: Kind from the tags file (may be empty).
        name: Tag name field.
        scope: Scope field from ctags.
        pattern: Search pattern (e.g. ``/^bool Foo::bar() {$/``).

    Returns:
        Normalized kind string such as ``function``, ``class``, ``namespace``.
    """
    kind = raw_kind.strip().lower()
    if kind:
        if kind in {"f", "function"}:
            return "function"
        if kind in {"c", "class"}:
            return "class"
        if kind in {"s", "struct"}:
            return "struct"
        if kind in {"n", "namespace"}:
            return "namespace"
        if kind in {"m", "member"}:
            return "method"
        if kind in {"e", "enum"}:
            return "enum"
        return kind

    lowered_pattern = pattern.lower()
    if "::" in name and "(" in pattern:
        return "function"
    if scope and ("::" in scope or scope):
        if "(" in pattern or "{" in pattern:
            return "function"
        if lowered_pattern.startswith("class ") or lowered_pattern.startswith("struct "):
            return "class" if lowered_pattern.startswith("class ") else "struct"
    if lowered_pattern.startswith("namespace "):
        return "namespace"
    if lowered_pattern.startswith("class "):
        return "class"
    if lowered_pattern.startswith("struct "):
        return "struct"
    if lowered_pattern.startswith("enum "):
        return "enum"
    if "(" in pattern:
        return "function"
    return "unknown"


def _join_scope(scope: str, name: str) -> str:
    """Join scope and name into a ``::`` qualified segment without duplication.

    Args:
        scope: Parent qualifier (e.g. ``A::B::Foo``).
        name: Child name (e.g. ``isApprox``).

    Returns:
        Combined qualified string.
    """
    if not scope:
        return name
    if name.startswith(scope + "::"):
        return name
    if scope.endswith("::" + name):
        return scope
    return f"{scope}::{name}"


def _qualified_name_from_pattern(pattern: str) -> str:
    """Extract a qualified name fragment from a ctags exuberant pattern.

    Parses ``namespace A::B {``, ``class Foo {``, and ``bool Foo::bar(`` forms.

    Args:
        pattern: Ctags pattern field (slash-delimited regex).

    Returns:
        Extracted qualifier or ``""`` when not recognized.
    """
    if not pattern:
        return ""
    body = pattern.strip("/")
    if body.startswith("^"):
        body = body[1:]
    for prefix in ("namespace ", "class ", "struct ", "enum "):
        if body.startswith(prefix):
            rest = body[len(prefix) :]
            for end in (" {", " {$", "{"):
                if end in rest:
                    return rest.split(end, 1)[0].strip()
    match = re.match(r"^[\w:]+\s+([\w:]+)::([\w~]+)\s*\(", body)
    if match:
        return f"{match.group(1)}::{match.group(2)}"
    return ""


def build_qualified_name(
    name: str,
    scope: str,
    class_field: str = "",
    namespace_field: str = "",
    enum_field: str = "",
    interface_field: str = "",
) -> str:
    """Build a fully qualified C++ symbol name from ctags extension fields.

    Prefers already-qualified ``name`` values, then ``class``/``namespace``
    fields from ctags, then the generic ``scope`` string.

    Args:
        name: Tag name (may already contain ``::``).
        scope: Scope field from ctags.
        class_field: ``class:`` extension (bytes-decoded).
        namespace_field: ``namespace:`` extension.
        enum_field: ``enum:`` extension.
        interface_field: ``interface:`` extension.

    Returns:
        Best-effort qualified name for symbol keys and reports.
    """
    if "::" in name:
        return name

    container = class_field or interface_field or struct_field(enum_field)
    if container:
        if name in container or container.endswith("::" + name):
            return container if name == container.split("::")[-1] else _join_scope(container, name)
        return _join_scope(container, name)

    if namespace_field:
        return _join_scope(namespace_field, name)

    if scope:
        return _join_scope(scope, name)

    return name


def struct_field(enum_field: str) -> str:
    """Return enum_field as struct container alias (ctags uses enum for both).

    Args:
        enum_field: Enum/struct container from ctags.

    Returns:
        Same string; exists to clarify intent at call sites.
    """
    return enum_field


def normalize_scope_parts(*parts: str) -> str:
    """Merge multiple scope fragments without duplicating ``::`` segments.

    Args:
        *parts: Scope strings in outer-to-inner order.

    Returns:
        Single merged scope string.
    """
    cleaned = [p for p in parts if p]
    if not cleaned:
        return ""
    result = cleaned[0]
    for part in cleaned[1:]:
        if part.startswith(result + "::"):
            result = part
        elif not result.endswith("::" + part) and part != result:
            result = _join_scope(result, part)
    return result


def symbol_key_from_tag_fields(
    *,
    name: str,
    raw_kind: str,
    scope: str,
    class_field: str,
    namespace_field: str,
    enum_field: str,
    interface_field: str,
    pattern: str,
    _file_scope: bool,
) -> tuple[SymbolKey, str, str]:
    """Construct a :class:`SymbolKey` and display fields from raw ctags columns.

    Called once per tag row in :func:`~semantic_branch_diff.ctags_adapter._read_tags_file`.
    Combines kind inference, qualified name building, and pattern fallbacks.

    Args:
        name: Tag name.
        raw_kind: Raw kind from ctags.
        scope: Scope field.
        class_field: Class extension field.
        namespace_field: Namespace extension field.
        enum_field: Enum extension field.
        interface_field: Interface extension field.
        pattern: Ctags pattern.
        _file_scope: Whether tag is file-scoped (reserved for future use).

    Returns:
        Tuple ``(key, short_name, norm_scope)`` for building a :class:`Symbol`.
    """
    kind = effective_kind(raw_kind, name, scope, pattern)
    if "::" in name:
        qualified = name
    elif kind == "namespace":
        qualified = _qualified_name_from_pattern(pattern) or build_qualified_name(
            name,
            scope,
            class_field=class_field,
            namespace_field=namespace_field,
            enum_field=enum_field,
            interface_field=interface_field,
        )
    else:
        qualified = build_qualified_name(
            name,
            scope,
            class_field=class_field,
            namespace_field=namespace_field,
            enum_field=enum_field,
            interface_field=interface_field,
        )
        if kind in FUNCTION_KINDS and "::" not in qualified:
            pattern_qn = _qualified_name_from_pattern(pattern)
            if pattern_qn.endswith("::" + name):
                qualified = _join_scope(
                    class_field or pattern_qn.rsplit("::", 1)[0],
                    name,
                )
    signature = pattern.strip() if pattern else None
    key = SymbolKey(kind=kind, qualified_name=qualified, signature=signature)
    short_name = qualified.split("::")[-1] if qualified else name
    norm_scope = qualified.rsplit("::", 1)[0] if "::" in qualified else scope
    return key, short_name, norm_scope


def deduplicate_symbols(symbols: Iterable[Symbol]) -> list[Symbol]:
    """Remove duplicate ctags rows for the same logical symbol.

    Ctags ``--extras=+q`` can emit both qualified and unqualified tags.
    Prefers qualified names, higher kind priority, and smaller ranges.

    Args:
        symbols: Raw symbol list from one tags file.

    Returns:
        Filtered list with duplicates removed.
    """
    by_qualified: dict[tuple[str, str, int], Symbol] = {}
    for sym in symbols:
        bucket = (sym.kind, sym.qualified_name, sym.start_line)
        existing = by_qualified.get(bucket)
        if existing is None:
            by_qualified[bucket] = sym
            continue
        if _symbol_preference(sym, existing):
            by_qualified[bucket] = sym

    result = list(by_qualified.values())
    filtered: list[Symbol] = []
    for sym in result:
        if any(
            other is not sym
            and other.kind == sym.kind
            and other.start_line == sym.start_line
            and other.end_line == sym.end_line
            and "::" in other.qualified_name
            and "::" not in sym.qualified_name
            for other in result
        ):
            continue
        filtered.append(sym)
    return filtered


def _symbol_preference(candidate: Symbol, incumbent: Symbol) -> bool:
    """Return whether ``candidate`` should replace ``incumbent`` in deduplication.

    Args:
        candidate: New symbol under consideration.
        incumbent: Symbol already stored for the bucket.

    Returns:
        ``True`` when candidate is strictly preferred.
    """
    if "::" in candidate.qualified_name and "::" not in incumbent.qualified_name:
        return True
    c_pri = KIND_PRIORITY.get(candidate.kind, 99)
    i_pri = KIND_PRIORITY.get(incumbent.kind, 99)
    if c_pri != i_pri:
        return c_pri < i_pri
    return candidate.range_size() <= incumbent.range_size()


def kind_priority(kind: str) -> int:
    """Return sort priority for symbol kind (lower = more specific).

    Args:
        kind: Normalized kind string.

    Returns:
        Priority integer from :data:`KIND_PRIORITY`, or 99 if unknown.
    """
    return KIND_PRIORITY.get(kind, 99)


def best_enclosing_symbol(symbols: list[Symbol], line: int) -> Symbol | None:
    """Pick the innermost, highest-priority symbol containing ``line``.

    Used by the diff engine to attribute changed lines to functions instead of
    enclosing namespaces when ranges overlap.

    Args:
        symbols: All symbols in one file revision.
        line: 1-based changed line number.

    Returns:
        Best matching :class:`Symbol`, or ``None`` for file-scope changes.
    """
    candidates = [s for s in symbols if s.contains_line(line) and not s.file_scope]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: (kind_priority(s.kind), s.range_size(), s.start_line),
    )


@dataclass
class LineAttribution:
    """Accumulator mapping changed lines to symbols or file scope.

    Attributes:
        symbol_keys: Set of symbol keys touched by attributed lines.
        file_scope_lines: Lines outside any symbol range.
    """

    symbol_keys: set[SymbolKey] = field(default_factory=set)
    file_scope_lines: list[int] = field(default_factory=list)

    def add_line(self, line: int, symbol: Symbol | None) -> None:
        """Record one changed line under a symbol or file-scope bucket.

        Args:
            line: 1-based line number.
            symbol: Enclosing symbol from :func:`best_enclosing_symbol`, or ``None``.
        """
        if symbol is None:
            self.file_scope_lines.append(line)
        else:
            self.symbol_keys.add(symbol.key)
