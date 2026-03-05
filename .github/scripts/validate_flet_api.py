#!/usr/bin/env python3
"""Validate X-Ray Flet code against Flet 0.80.2+ API compatibility.

This script checks for deprecated/invalid Flet parameters before runtime.
Run this pre-launch to catch API breaks statically.

Usage:
    python .github/scripts/validate_flet_api.py
"""

import ast
import inspect
import re
import sys
from pathlib import Path

import flet as ft


# Known Flet 0.80.2 API changes
API_MIGRATIONS = {
    "TextField": {
        "font_family": None,  # Removed, use text_style=ft.TextStyle(font_family=...)
        "text_style": "supported",
    },
    "Border": {
        "left": None,  # Removed, use Border.only(left=BorderSide(...))
        "only": "supported",
    },
    "Padding": {
        "symmetric": "requires_kwargs",  # Must use vertical=, horizontal= (no positional)
    },
    "Text": {
        "font_family": None,  # Removed, use style=ft.TextStyle(font_family=...)
        "style": "supported",
    },
}


def get_widget_params(widget_name: str) -> set:
    """Get valid parameters for a Flet widget class."""
    try:
        widget_class = getattr(ft, widget_name)
        sig = inspect.signature(widget_class.__init__)
        return set(sig.parameters.keys()) - {"self"}
    except (AttributeError, ValueError):
        return set()


def check_file(filepath: Path) -> list[str]:
    """Check a Python file for Flet API issues.

    Returns list of issues found.
    """
    issues = []

    try:
        with open(filepath, encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        return [f"{filepath}: Parse error: {e}"]

    # Pattern: ft.WidgetName(param=value)
    for line_num, line in enumerate(content.split("\n"), 1):
        # Skip comment lines and strings
        if line.strip().startswith("#"):
            continue

        # Check for deprecated font_family in TextField (not in text_style=)
        if "ft.TextField" in line and "font_family" in line:
            # Make sure it's not inside text_style=ft.TextStyle(font_family=...)
            if not re.search(r"text_style\s*=\s*ft\.TextStyle\(.*font_family", line):
                issues.append(
                    f"{filepath}:{line_num}: TextField uses deprecated 'font_family' "
                    "(use text_style=ft.TextStyle(font_family=...) instead)"
                )

        # Check for deprecated font_family in Text (not in style=)
        # NOTE: ft.Text still accepts font_family in 0.80.2; only ft.TextField broke.
        # Keeping this commented out for future reference.
        # if "ft.Text" in line and "font_family" in line:
        #     if not re.search(r"style\s*=\s*ft\.TextStyle\(.*font_family", line):
        #         issues.append(...)

        # Check for Border.left()
        if "ft.Border.left" in line:
            issues.append(
                f"{filepath}:{line_num}: Border.left() removed "
                "(use Border.only(left=BorderSide(...)) instead)"
            )

        # Check for Padding.symmetric with positional args (heuristic)
        if "ft.Padding.symmetric" in line and re.search(
            r"Padding\.symmetric\(\s*\d+\s*,\s*\d+", line
        ):
            issues.append(
                f"{filepath}:{line_num}: Padding.symmetric() uses positional args "
                "(use vertical=..., horizontal=... keyword args instead)"
            )

        # Check for wrap=True on ft.Row — broken in Flet 0.80.2
        # Causes WrapParentData vs FlexParentData crash
        if re.search(r"ft\.Row\(.*wrap\s*=\s*True", line) or (
            "wrap=True" in line
            and any(kw in content.split("\n")[max(0, line_num - 5) : line_num]
                    for kw in ["ft.Row("] if kw)
        ):
            # Simple heuristic: line itself has both ft.Row and wrap=True
            if "ft.Row" in line and "wrap=True" in line:
                issues.append(
                    f"{filepath}:{line_num}: ft.Row uses wrap=True "
                    "(broken in Flet 0.80.2 — causes WrapParentData crash. "
                    "Use scroll=ft.ScrollMode.AUTO instead)"
                )

    return issues


def main():
    """Validate all Flet usage in x_ray_flet.py and UI/tabs."""
    root = Path(__file__).parent.parent.parent

    # Files to check
    check_files = [
        root / "x_ray_flet.py",
        *sorted((root / "UI" / "tabs").glob("*.py")),
    ]

    all_issues = []
    for fpath in check_files:
        if fpath.exists():
            issues = check_file(fpath)
            all_issues.extend(issues)

    if all_issues:
        print("Flet API Compatibility Issues Found:")
        print("=" * 70)
        for issue in sorted(all_issues):
            print(issue)
        print("=" * 70)
        print(f"Total issues: {len(all_issues)}")
        return 1
    else:
        print("No Flet API compatibility issues found.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
