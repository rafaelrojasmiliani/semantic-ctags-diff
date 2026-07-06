"""Optional PyDriller/Lizard method metadata enrichment.

Cross-checks ctags symbol results with Lizard static analysis to attach
complexity and size metrics to modified symbols. This layer is optional and
never replaces ctags-based symbol detection.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def enrich_modified_symbol(
    *,
    _repo_path: str,
    old_content: str | None,
    new_content: str | None,
    file_path: str,
    qualified_name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Attach Lizard method metrics to a modified symbol when enrichment is enabled.

    Called from :func:`semantic_branch_diff.diff_engine.analyze_file_diff` for
    each symbol classified as modified. Matches Lizard function names against
    the ctags ``qualified_name`` (suffix match on ``::method``).

    Methodology: parse source with Lizard, scan ``function_list``, pick the
    entry whose name matches the qualified symbol, and record nloc/complexity.

    Args:
        _repo_path: Repository path (reserved for future PyDriller traversal).
        old_content: File text at merge-base, or ``None`` for added files.
        new_content: File text at head, or ``None`` for deleted files.
        file_path: Repo-relative path (passed to Lizard for language detection).
        qualified_name: Fully qualified ctags symbol name to match.
        enabled: When ``False``, return immediately without importing Lizard.

    Returns:
        Dict keyed by ``"old"`` / ``"new"`` with metric dicts, or ``{}`` when
        enrichment is disabled, Lizard is missing, or no match is found.
    """
    if not enabled or not new_content:
        return {}

    try:
        from lizard import analyze_file
    except ImportError:
        logger.debug("lizard not available for method enrichment")
        return {}

    metrics: dict[str, Any] = {}
    # Analyze both revisions so callers can compare complexity across the diff.
    for label, content in (("new", new_content), ("old", old_content)):
        if not content:
            continue
        try:
            info = analyze_file.analyze_source_code(file_path, content)
        except Exception as exc:  # ponytail: best-effort enrichment only
            logger.debug("lizard analyze failed for %s: %s", file_path, exc)
            continue
        # Find the Lizard function entry that corresponds to this ctags symbol.
        for func in info.function_list:
            method_name = func.name
            if method_name == qualified_name or qualified_name.endswith("::" + method_name):
                metrics[label] = {
                    "nloc": func.nloc,
                    "complexity": func.cyclomatic_complexity,
                    "parameters": len(func.parameters) if func.parameters else 0,
                    "start_line": func.start_line,
                    "end_line": func.end_line,
                }
                break
    return metrics
