#!/usr/bin/env python3
"""Update uv, ruff, and ty to their latest stable releases.

Usage:
    python update_tools.py          # update all three
    python update_tools.py --check  # show current versions only
"""
import subprocess
import sys


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    try:
        result = subprocess.run(cmd, timeout=120)
        return result.returncode == 0
    except FileNotFoundError:
        print(f"  [ERROR] {cmd[0]!r} not found on PATH.")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [ERROR] {label} timed out.")
        return False


def show_versions():
    print("\nInstalled versions:")
    for cmd, name in [
        (["uv", "--version"], "uv"),
        (["ruff", "--version"], "ruff"),
        (["ty", "--version"], "ty"),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            ver = r.stdout.strip() or r.stderr.strip()
            print(f"  {name}: {ver}")
        except FileNotFoundError:
            print(f"  {name}: not installed")
        except subprocess.TimeoutExpired:
            print(f"  {name}: timed out")


def main():
    if "--check" in sys.argv:
        show_versions()
        return

    ok = True
    # uv: try self update first (standalone install), fall back to pip
    if not run(["uv", "self", "update"], "Updating uv (standalone)"):
        ok &= run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "uv"],
            "Updating uv (pip)",
        )
    ok &= run(["uv", "tool", "upgrade", "ruff"], "Updating ruff")
    ok &= run(["uv", "tool", "upgrade", "ty"], "Updating ty")

    show_versions()

    if ok:
        print("\n✓ All tools updated successfully.")
    else:
        print("\n⚠ Some updates failed — see errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
