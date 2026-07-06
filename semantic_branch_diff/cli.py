"""Command-line interface for semantic-branch-diff.

Parses user arguments, invokes :func:`semantic_branch_diff.diff_engine.semantic_diff`,
and writes JSON or Markdown to stdout or ``--out``. Debug logs always go to stderr
so stdout remains machine-readable for Vim ``:read !`` integration.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from semantic_branch_diff.diff_engine import DEFAULT_EXTENSIONS, semantic_diff
from semantic_branch_diff.renderers import render_json, render_markdown

logger = logging.getLogger(__name__)


def _parse_extensions(value: str) -> tuple[str, ...]:
    """Normalize a comma-separated extension list from the CLI.

    Used by ``--include`` so callers can pass ``cpp,hpp`` or ``.cpp,.hpp``.
    Ensures every entry starts with ``.`` for suffix matching in the diff engine.

    Args:
        value: Raw string from ``argparse`` (e.g. ``".c,.cpp,.h"``).

    Returns:
        Tuple of normalized extensions, each beginning with ``.``.
    """
    # Split on commas and drop empty tokens from trailing commas.
    parts = [p.strip() for p in value.split(",") if p.strip()]
    normalized: list[str] = []
    for part in parts:
        # Prepend dot when the user omitted it (``cpp`` -> ``.cpp``).
        normalized.append(part if part.startswith(".") else f".{part}")
    return tuple(normalized)


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``semantic-branch-diff`` argument parser.

    Centralizes all CLI flags so ``main`` and tests can share the same schema.
    Defaults mirror the package spec (JSON output, ``HEAD`` as head ref, etc.).

    Returns:
        Configured :class:`argparse.ArgumentParser` ready for ``parse_args``.
    """
    parser = argparse.ArgumentParser(
        prog="semantic-branch-diff",
        description="Semantic branch diff using ctags and Git",
    )
    parser.add_argument("--repo", required=True, help="Local Git repository path")
    parser.add_argument("--base", required=True, help="Base branch/ref")
    parser.add_argument("--head", default="HEAD", help="Head branch/ref")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Output format",
    )
    parser.add_argument("--out", help="Optional output file path")
    parser.add_argument("--ctags", default="ctags", help="ctags executable path")
    parser.add_argument(
        "--include",
        default=",".join(DEFAULT_EXTENSIONS),
        help="Comma-separated file extensions to analyze",
    )
    parser.add_argument(
        "--max-diff-lines",
        type=int,
        default=None,
        help="Optional truncation for raw line excerpts (reserved)",
    )
    parser.add_argument(
        "--no-pydriller-methods",
        action="store_true",
        help="Disable PyDriller/Lizard method enrichment",
    )
    parser.add_argument(
        "--with-difftastic",
        action="store_true",
        help="Attach structural excerpts via difftastic (placeholder)",
    )
    parser.add_argument("--debug", action="store_true", help="Debug logging to stderr")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point registered as the ``semantic-branch-diff`` console script.

    Workflow: parse args -> run semantic diff -> render -> write stdout/file.
    Returns exit code 1 on fatal errors so shell/Vim can detect failure.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]`` when ``None``.

    Returns:
        ``0`` on success, ``1`` when the diff pipeline raises.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Route logs to stderr; stdout is reserved for the report body.
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    else:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        # Delegate branch comparison and symbol analysis to the core API.
        result = semantic_diff(
            repo=args.repo,
            base=args.base,
            head=args.head,
            ctags_executable=args.ctags,
            extensions=_parse_extensions(args.include),
            use_pydriller_methods=not args.no_pydriller_methods,
            debug=args.debug,
            with_difftastic=args.with_difftastic,
        )
    except Exception as exc:
        logger.error("%s", exc)
        if args.debug:
            logger.exception("fatal error")
        print(str(exc), file=sys.stderr)
        return 1

    # Serialize to the requested format (stable sorted JSON or human Markdown).
    output = render_json(result) if args.format == "json" else render_markdown(result)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
