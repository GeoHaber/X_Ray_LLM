#!/usr/bin/env python3
"""Bump version across pyproject.toml, Cargo.toml, and xray/__init__.py atomically."""

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

FILES = {
    "pyproject.toml": re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
    "scanner/Cargo.toml": re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE),
    "xray/__init__.py": re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE),
}


def bump(new_version: str, *, dry_run: bool = False) -> None:
    for relpath, pattern in FILES.items():
        filepath = ROOT / relpath
        if not filepath.exists():
            print(f"SKIP  {relpath} (not found)")
            continue

        text = filepath.read_text(encoding="utf-8")
        match = pattern.search(text)
        if not match:
            print(f"SKIP  {relpath} (no version pattern found)")
            continue

        old = match.group(1)
        updated = pattern.sub(f'version = "{new_version}"' if "toml" in relpath else f'__version__ = "{new_version}"', text, count=1)
        if dry_run:
            print(f"DRY   {relpath}: {old} -> {new_version}")
        else:
            filepath.write_text(updated, encoding="utf-8")
            print(f"BUMP  {relpath}: {old} -> {new_version}")


def main():
    parser = argparse.ArgumentParser(description="Bump X-Ray version across all manifests")
    parser.add_argument("version", help="New version string (e.g. 0.3.0)")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing")
    args = parser.parse_args()

    # Basic semver validation
    if not re.match(r"^\d+\.\d+\.\d+(-[\w.]+)?$", args.version):
        print(f"ERROR: '{args.version}' is not a valid semver string", file=sys.stderr)
        sys.exit(1)

    bump(args.version, dry_run=args.dry_run)
    print("\nDone.")


if __name__ == "__main__":
    main()
