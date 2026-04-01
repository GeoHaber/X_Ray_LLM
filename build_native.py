#!/usr/bin/env python3
"""Build the xray_native PyO3 extension using maturin."""

import subprocess
import sys


def main() -> None:
    release = "release" in sys.argv[1:]

    print("=" * 60)
    print("Building xray_native PyO3 extension")
    print(f"  Mode: {'release' if release else 'development'}")
    print("=" * 60)

    cmd = [sys.executable, "-m", "maturin", "develop", "--features", "python"]
    if release:
        cmd.append("--release")

    try:
        subprocess.run(cmd, cwd="scanner", check=True)
    except FileNotFoundError:
        print("\nError: maturin not found.")
        print("Install it with:  pip install maturin")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed with exit code {e.returncode}")
        sys.exit(1)

    print()
    print("Build successful!")
    print("You can now: from xray.native_bridge import scan_file, scan_directory")
    print("=" * 60)


if __name__ == "__main__":
    main()
