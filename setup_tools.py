#!/usr/bin/env python3
"""Bootstrap X-Ray LLM: install uv, then install ruff + ty via uv.

Usage:
    python setup_tools.py          # install everything
    python setup_tools.py --check  # verify what's installed

uv is installed via the official Astral standalone installer so that
``uv self update`` works.  See https://docs.astral.sh/uv/getting-started/installation/
"""
import os
import platform
import shutil
import subprocess
import sys


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def install_uv_standalone():
    """Install uv via the official Astral standalone installer."""
    if platform.system() == "Windows":
        subprocess.check_call(
            ["powershell", "-ExecutionPolicy", "ByPass", "-c",
             "irm https://astral.sh/uv/install.ps1 | iex"],
        )
        # Ensure the install dir is on PATH for this process
        local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin")
        if local_bin not in os.environ.get("PATH", ""):
            os.environ["PATH"] = local_bin + os.pathsep + os.environ["PATH"]
    else:
        subprocess.check_call(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"])


def main():
    check_only = "--check" in sys.argv

    # 1. uv
    if not has("uv"):
        if check_only:
            print("uv: NOT INSTALLED")
        else:
            print("Installing uv via standalone installer …")
            install_uv_standalone()
    else:
        v = subprocess.run(["uv", "--version"], capture_output=True, text=True)
        print(f"uv: {v.stdout.strip()}")

    if check_only:
        for tool in ("ruff", "ty"):
            if has(tool):
                v = subprocess.run([tool, "--version"], capture_output=True, text=True)
                print(f"{tool}: {v.stdout.strip()}")
            else:
                print(f"{tool}: NOT INSTALLED")
        return

    # 2. ruff + ty via uv
    for tool in ("ruff", "ty"):
        print(f"Installing/upgrading {tool} …")
        subprocess.run(["uv", "tool", "install", tool], timeout=120)

    # 3. Verify
    print("\nInstalled versions:")
    for tool in ("uv", "ruff", "ty"):
        try:
            v = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=10)
            print(f"  {tool}: {v.stdout.strip()}")
        except FileNotFoundError:
            print(f"  {tool}: not found")


if __name__ == "__main__":
    main()
