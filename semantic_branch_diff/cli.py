"""Command-line interface for semantic-branch-diff.

Parses user arguments, invokes :func:`semantic_branch_diff.diff_engine.semantic_diff`,
and writes JSON or Markdown to stdout or ``--out``. Debug logs always go to stderr
so stdout remains machine-readable for Vim ``:read !`` integration.

Comparison modes:

- ``--repo`` + ``--base`` + ``--head`` — merge-request style (merge-base..head)
- ``--repo`` + ``--from`` + ``--to`` — direct commit-to-commit
- ``--old-dir`` + ``--new-dir`` — directory snapshots (examples, no Git)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from semantic_branch_diff.diff_engine import DEFAULT_EXTENSIONS, semantic_diff
from semantic_branch_diff.navigation import symbol_at_path
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
    parts = [p.strip() for p in value.split(",") if p.strip()]
    normalized: list[str] = []
    for part in parts:
        normalized.append(part if part.startswith(".") else f".{part}")
    return tuple(normalized)


def build_parser() -> argparse.ArgumentParser:
    """Construct the ``semantic-branch-diff`` argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` ready for ``parse_args``.
    """
    parser = argparse.ArgumentParser(
        prog="semantic-branch-diff",
        description="Semantic diff using ctags (branches, commits, or directory snapshots)",
    )
    parser.add_argument("--repo", help="Local Git repository path (Git modes)")
    parser.add_argument("--base", default="main", help="Base branch/ref (MR mode)")
    parser.add_argument("--head", default="HEAD", help="Head branch/ref (MR mode)")
    parser.add_argument("--from", dest="from_ref", metavar="REF", help="From commit/ref (direct mode)")
    parser.add_argument("--to", dest="to_ref", metavar="REF", help="To commit/ref (direct mode)")
    parser.add_argument(
        "--no-merge-base",
        action="store_true",
        help="Compare base..head directly without merge-base (with --base/--head)",
    )
    parser.add_argument("--old-dir", help="Old directory tree (snapshot mode)")
    parser.add_argument("--new-dir", help="New directory tree (snapshot mode)")
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
    parser.add_argument(
        "--path",
        action="append",
        metavar="FILE",
        help="Limit Git diff to repo-relative file path (repeatable)",
    )
    parser.add_argument(
        "--symbol-at",
        action="store_true",
        help="Resolve symbol at --file/--line (no branch diff; JSON to stdout)",
    )
    parser.add_argument("--file", metavar="PATH", help="Source file for --symbol-at")
    parser.add_argument("--line", type=int, metavar="N", help="1-based line for --symbol-at")
    parser.add_argument(
        "--kind",
        default="",
        help="Kind filter for --symbol-at: function, class, namespace, or symbol (default)",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    """Ensure the user passed a valid combination of mode flags."""
    if args.symbol_at or (args.file is not None and args.line is not None):
        if not args.file or args.line is None or args.line < 1:
            raise ValueError("symbol-at mode requires --file PATH and --line N (N >= 1)")
        return

    snapshot = bool(args.old_dir or args.new_dir)
    git_direct = bool(args.from_ref or args.to_ref)
    git_mr = bool(args.repo)

    if snapshot:
        if not args.old_dir or not args.new_dir:
            raise ValueError("snapshot mode requires both --old-dir and --new-dir")
        if git_mr or git_direct:
            raise ValueError("use either snapshot mode (--old-dir/--new-dir) or Git mode (--repo), not both")
        return

    if not args.repo:
        raise ValueError("Git mode requires --repo, or use --old-dir and --new-dir for snapshots")

    if git_direct and (args.from_ref is None or args.to_ref is None):
        raise ValueError("direct Git mode requires both --from and --to")


def _run_symbol_at(args: argparse.Namespace) -> int:
    """Emit JSON for symbol-at-line resolution (Vim Flog integration)."""
    assert args.file is not None and args.line is not None
    result = symbol_at_path(
        Path(args.file),
        args.line,
        ctags_executable=args.ctags,
        kind_filter=args.kind,
    )
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point registered as the ``semantic-branch-diff`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    else:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    try:
        _validate_args(args)
    except Exception as exc:
        logger.error("%s", exc)
        print(str(exc), file=sys.stderr)
        return 1

    if args.symbol_at or (args.file is not None and args.line is not None):
        try:
            return _run_symbol_at(args)
        except Exception as exc:
            logger.error("%s", exc)
            if args.debug:
                logger.exception("fatal error")
            print(str(exc), file=sys.stderr)
            return 1

    try:
        result = semantic_diff(
            repo=args.repo,
            base=args.base,
            head=args.head,
            from_ref=args.from_ref,
            to_ref=args.to_ref,
            use_merge_base=not args.no_merge_base,
            old_dir=args.old_dir,
            new_dir=args.new_dir,
            ctags_executable=args.ctags,
            extensions=_parse_extensions(args.include),
            use_pydriller_methods=not args.no_pydriller_methods,
            debug=args.debug,
            with_difftastic=args.with_difftastic,
            paths=tuple(args.path or ()),
        )
    except Exception as exc:
        logger.error("%s", exc)
        if args.debug:
            logger.exception("fatal error")
        print(str(exc), file=sys.stderr)
        return 1

    output = render_json(result) if args.format == "json" else render_markdown(result)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
