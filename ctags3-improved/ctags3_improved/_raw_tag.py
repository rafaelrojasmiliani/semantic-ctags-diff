"""Private tags-file row packaging (not part of the public API).

Bundles undecorated ctags columns so normalize/adapters pass one object
instead of a long keyword list. Do not import this module from outside
``ctags3_improved``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ctags3_improved.model import FUNCTION_KINDS, MEMBER_KINDS, Symbol, SymbolKey
from ctags3_improved.normalize import (
    _join_scope,
    _qualified_name_from_pattern,
    build_qualified_name,
    effective_kind,
)


@dataclass
class _RawTag:
    """One undecorated tags-file row before normalization."""

    name: str
    raw_kind: str
    scope: str = ""
    class_field: str = ""
    namespace_field: str = ""
    enum_field: str = ""
    interface_field: str = ""
    pattern: str = ""
    line: int = 0
    end_raw: str = ""
    file_scope: bool = False


def _key_from_raw(tag: _RawTag) -> tuple[SymbolKey, str, str]:
    """Build :class:`SymbolKey`, short name, and normalized scope from ``tag``."""
    kind = effective_kind(tag.raw_kind, tag.name, tag.scope, tag.pattern)
    if kind in MEMBER_KINDS and not (tag.class_field or tag.interface_field):
        kind = "variable"
    if "::" in tag.name:
        qualified = tag.name
    elif kind == "namespace":
        qualified = _qualified_name_from_pattern(tag.pattern) or build_qualified_name(
            tag.name,
            tag.scope,
            class_field=tag.class_field,
            namespace_field=tag.namespace_field,
            enum_field=tag.enum_field,
            interface_field=tag.interface_field,
        )
    else:
        qualified = build_qualified_name(
            tag.name,
            tag.scope,
            class_field=tag.class_field,
            namespace_field=tag.namespace_field,
            enum_field=tag.enum_field,
            interface_field=tag.interface_field,
        )
        if kind in FUNCTION_KINDS and "::" not in qualified:
            pattern_qn = _qualified_name_from_pattern(tag.pattern)
            if pattern_qn.endswith("::" + tag.name):
                qualified = _join_scope(
                    tag.class_field or pattern_qn.rsplit("::", 1)[0],
                    tag.name,
                )
    signature = tag.pattern.strip() if tag.pattern else None
    key = SymbolKey(kind=kind, qualified_name=qualified, signature=signature)
    short_name = qualified.split("::")[-1] if qualified else tag.name
    norm_scope = qualified.rsplit("::", 1)[0] if "::" in qualified else tag.scope
    return key, short_name, norm_scope


def _symbol_from_raw(tag: _RawTag, *, path: str, end_line: int) -> Symbol:
    """Turn a raw tags row into a public :class:`Symbol`."""
    key, short_name, norm_scope = _key_from_raw(tag)
    return Symbol(
        key=key,
        name=short_name,
        qualified_name=key.qualified_name,
        kind=key.kind,
        raw_kind=tag.raw_kind,
        scope=norm_scope,
        path=path,
        start_line=tag.line,
        end_line=max(end_line, tag.line),
        file_scope=tag.file_scope,
        pattern=tag.pattern or None,
        signature=key.signature,
    )
