"""Core/cli_args.py — Shared CLI argument definitions for X-Ray entry points.

Consolidates the ``--path``, ``--smell``, ``--duplicates``, ``--lint``,
``--security``, ``--full-scan``, ``--rustify``, ``--report``, ``--exclude``
flags that were duplicated across ``x_ray_claude.py`` and ``x_ray_exe.py``.
"""

from __future__ import annotations

import argparse


def add_common_scan_args(parser: argparse.ArgumentParser) -> None:
    """Register the common scan flags on *parser*.

    Each entry point may add extra flags (``--interactive``, ``--hw``, etc.)
    before or after calling this helper.
    """
    parser.add_argument("--path", default=".", help="Root directory to scan")
    parser.add_argument("--smell", action="store_true", help="Run code smell detection")
    parser.add_argument(
        "--duplicates", action="store_true", help="Run duplicate detection"
    )
    parser.add_argument("--format", action="store_true", help="Run Ruff format check")
    parser.add_argument("--lint", action="store_true", help="Run Ruff linter analysis")
    parser.add_argument(
        "--security", action="store_true", help="Run Bandit security scan"
    )
    parser.add_argument("--full-scan", action="store_true", help="Run ALL analyses")
    parser.add_argument(
        "--rustify",
        action="store_true",
        help="Rank functions by Rust-porting suitability",
    )
    parser.add_argument("--report", help="Save JSON report to file")
    parser.add_argument("--exclude", nargs="*", help="Exclude directories")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix Ruff lint issues after analysis (implies --lint)",
    )
    parser.add_argument(
        "--fix-smells",
        action="store_true",
        help="Auto-repair common code smells: comment out console.log/debug "
        "prints, create missing project files (.gitignore, LICENSE, etc.)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Scan JS/TS/JSX/TSX files for web-specific code smells",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run project health & structural completeness check",
    )
    parser.add_argument(
        "--gen-tests",
        action="store_true",
        help="Auto-generate monkey tests from analysis data (pytest for Python, "
        "Vitest for JS/TS). Writes to --test-output dir.",
    )
    parser.add_argument(
        "--test-output",
        metavar="DIR",
        default=".",
        help="Output directory for generated test files (default: project root)",
    )
    parser.add_argument(
        "--compare",
        metavar="PREV_REPORT",
        help="Path to a previous JSON report; prints score delta after scan",
    )
    parser.add_argument(
        "--typecheck",
        action="store_true",
        help="Run Pyright type checker to catch type errors",
    )


def normalize_scan_args(
    args: argparse.Namespace, *, extra_flags: tuple[str, ...] = ()
) -> argparse.Namespace:
    """Apply default-selection logic shared across entry points.

    * If ``--full-scan`` is set, enables smell + lint + security + duplicates.
    * If *no* specific flag is active (including any names in *extra_flags*),
      defaults to smell + lint + security.

    Returns *args* (mutated in-place) for convenience.
    """
    specific = any(
        getattr(args, f, False)
        for f in (
            "smell",
            "duplicates",
            "lint",
            "security",
            "rustify",
            "web",
            "health",
            "typecheck",
            *extra_flags,
        )
    )
    if args.full_scan or not specific:
        args.smell = True
        args.format = True
        args.lint = True
        args.security = True
        if args.full_scan:
            args.duplicates = True
            args.web = True
            args.health = True
            args.typecheck = True
    return args
