#!/usr/bin/env python3
"""Update uv, ruff, and ty to their latest stable releases.

Usage:
    python update_tools.py          # update all three
    python update_tools.py --check  # show current versions only
"""
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


def run(cmd: list[str], label: str) -> bool:
    logger.info("=" * 50)
    logger.info("  %s", label)
    logger.info("=" * 50)
    try:
        result = subprocess.run(cmd, timeout=120)
        return result.returncode == 0
    except FileNotFoundError:
        logger.error("  %r not found on PATH.", cmd[0])
        return False
    except subprocess.TimeoutExpired:
        logger.error("  %s timed out.", label)
        return False


def show_versions():
    logger.info("Installed versions:")
    for cmd, name in [
        (["uv", "--version"], "uv"),
        (["ruff", "--version"], "ruff"),
        (["ty", "--version"], "ty"),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            ver = r.stdout.strip() or r.stderr.strip()
            logger.info("  %s: %s", name, ver)
        except FileNotFoundError:
            logger.warning("  %s: not installed", name)
        except subprocess.TimeoutExpired:
            logger.warning("  %s: timed out", name)


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
        logger.info("All tools updated successfully.")
    else:
        logger.warning("Some updates failed — see errors above.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
