"""Kind inference, qualified-name building, and reportability filters."""

from __future__ import annotations

import re

from ctags3_improved.model import NOISE_KINDS


def effective_kind(raw_kind: str, name: str, scope: str, pattern: str) -> str:
    """Infer a normalized symbol kind when ctags emits an empty or terse kind."""
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
        if kind in {"m", "member", "field"}:
            # ctags 'm' is "class, struct, and union members" — a data field.
            return "member"
        if kind in {"l", "local"}:
            return "local"
        if kind in {"v", "variable"}:
            return "variable"
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


# Ctags names unnamed scopes ``anon`` + a hash, usually underscore-prefixed.
_ANONYMOUS_SEGMENT = re.compile(r"^_*anon[0-9a-f]*$", re.IGNORECASE)


def is_anonymous(qualified_name: str) -> bool:
    """Report whether a qualified name contains a ctags-generated anonymous scope."""
    return any(_ANONYMOUS_SEGMENT.match(part) for part in qualified_name.split("::"))


def is_reportable(kind: str, qualified_name: str) -> bool:
    """Report whether a symbol is worth showing to a human reviewer."""
    if kind in NOISE_KINDS:
        return False
    return not is_anonymous(qualified_name)


def _join_scope(scope: str, name: str) -> str:
    if not scope:
        return name
    if name.startswith(scope + "::"):
        return name
    if scope.endswith("::" + name):
        return scope
    return f"{scope}::{name}"


def _qualified_name_from_pattern(pattern: str) -> str:
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
    """Build a fully qualified C++ symbol name from ctags extension fields."""
    if "::" in name:
        return name

    container = class_field or interface_field or enum_field
    if container:
        if name in container or container.endswith("::" + name):
            return container if name == container.split("::")[-1] else _join_scope(container, name)
        return _join_scope(container, name)

    if namespace_field:
        return _join_scope(namespace_field, name)

    if scope:
        return _join_scope(scope, name)

    return name


def normalize_scope_parts(*parts: str) -> str:
    """Merge multiple scope fragments without duplicating ``::`` segments."""
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
