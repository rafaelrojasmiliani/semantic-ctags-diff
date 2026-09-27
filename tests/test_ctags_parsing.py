"""Compatibility shim — ctags parsing tests live in ctags3-improved."""

# Re-run via pytest collection of ctags3-improved/tests (see pyproject testpaths).
# Kept so older docs/CI references to this module path do not break imports.
from ctags3_improved.adapter import generate_symbols  # noqa: F401
