"""
verify_rust_compilation.py — Test if transpiled Rust code actually compiles
============================================================================

Takes the transpiled Python→Rust pairs from _training_ground/transpiled/pairs.jsonl,
generates a real Cargo project, runs `cargo check`, and reports:
  - How many functions compile cleanly
  - What compiler errors come up most
  - Which transpiler patterns produce bad Rust

This is the REAL test — not "does it look right" but "does rustc accept it".
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any

XRAY_ROOT = Path(__file__).resolve().parent
PAIRS_FILE = XRAY_ROOT / "_training_ground" / "transpiled" / "pairs.jsonl"
CRATE_DIR = XRAY_ROOT / "_verify_crate"

# Rust crates we reference in transpiled code
CARGO_TOML = """\
[package]
name = "xray_verify"
version = "0.1.0"
edition = "2021"

[dependencies]
regex = "1"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
chrono = "0.4"
log = "0.4"
env_logger = "0.10"
itertools = "0.12"
sha2 = "0.10"
md-5 = "0.10"
clap = { version = "4", features = ["derive"] }

[lib]
name = "xray_verify"
path = "src/lib.rs"
"""

# Common use statements that our transpiled code needs
COMMON_PRELUDE = """\
#![allow(unused_imports, unused_variables, dead_code, unused_mut,
         unused_assignments, unreachable_code, unused_parens,
         non_snake_case, unused_must_use, redundant_semicolons,
         clippy::all, non_camel_case_types, irrefutable_let_patterns)]

use std::collections::HashMap;
use std::collections::VecDeque;
use std::collections::BTreeMap;
use regex::Regex;
use sha2::{Sha256, Sha1, Sha512, Sha384, Digest};
use md5::Md5;

"""


def load_pairs(max_per_project: int = 0) -> List[Dict[str, Any]]:
    """Load transpiled pairs, optionally limiting per project."""
    pairs = []
    with open(PAIRS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            pairs.append(json.loads(line))

    if max_per_project > 0:
        by_project: Dict[str, List] = {}
        for p in pairs:
            by_project.setdefault(p["project"], []).append(p)
        selected = []
        for proj, items in by_project.items():
            # Pick clean ones first
            clean = [i for i in items if i.get("clean")]
            selected.extend(clean[:max_per_project])
        return selected

    # Only pick clean ones
    return [p for p in pairs if p.get("clean")]


def sanitize_fn_name(name: str, index: int) -> str:
    """Make a unique, valid Rust function name."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if safe and safe[0].isdigit():
        safe = f"fn_{safe}"
    if not safe:
        safe = "unnamed"
    return f"{safe}_{index}"


def generate_crate(pairs: List[Dict], batch_size: int = 200) -> List[Path]:
    """Generate a Cargo crate with all transpiled functions, split into modules.

    Returns list of module source files.
    """
    if CRATE_DIR.exists():
        shutil.rmtree(CRATE_DIR)
    src_dir = CRATE_DIR / "src"
    src_dir.mkdir(parents=True)

    # Write Cargo.toml
    (CRATE_DIR / "Cargo.toml").write_text(CARGO_TOML, encoding="utf-8")

    # Split into modules to avoid a single huge file
    modules = []
    for batch_idx in range(0, len(pairs), batch_size):
        batch = pairs[batch_idx : batch_idx + batch_size]
        mod_name = f"batch_{batch_idx // batch_size}"
        modules.append(mod_name)

        lines = [COMMON_PRELUDE]
        for i, pair in enumerate(batch):
            rust_code = pair.get("rust_code", "")
            if not rust_code or rust_code.startswith("// TRANSPILE ERROR"):
                continue

            # Deduplicate function names
            unique_name = sanitize_fn_name(pair.get("name", "unknown"), batch_idx + i)

            # Replace the function name in the Rust code to avoid conflicts
            rust_code = re.sub(
                r"^((?:async\s+)?fn\s+)\w+(\s*\()",
                f"\\1{unique_name}\\2",
                rust_code,
                count=1,
                flags=re.MULTILINE,
            )

            lines.append(
                f"// [{batch_idx + i}] {pair.get('name', '?')} from {pair.get('project', '?')}/{Path(pair.get('file', '?')).name}"
            )
            lines.append(rust_code)
            lines.append("")

        mod_path = src_dir / f"{mod_name}.rs"
        content = "\n".join(lines).replace("\r", "")
        mod_path.write_text(content, encoding="utf-8")

    # Write lib.rs
    lib_lines = ["// Auto-generated — cargo check verification\n"]
    for mod_name in modules:
        lib_lines.append(f"mod {mod_name};")
    (src_dir / "lib.rs").write_text("\n".join(lib_lines) + "\n", encoding="utf-8")

    return [src_dir / f"{m}.rs" for m in modules]


def run_cargo_check() -> tuple[int, str]:
    """Run cargo check and return (exit_code, stderr)."""
    result = subprocess.run(
        ["cargo", "check", "--message-format=short"],
        cwd=str(CRATE_DIR),
        capture_output=True,
        text=True,
        timeout=900,
    )
    return result.returncode, result.stderr


def parse_errors(stderr: str) -> List[Dict[str, str]]:
    """Parse cargo check errors from --message-format=short."""
    errors = []
    # Short format: src\batch_0.rs:42:5: error[E0425]: message
    # or:           src\batch_0.rs:42:5: error: message
    for m in re.finditer(
        r"(src[\\/]\w+\.rs):(\d+):\d+:\s*(error(?:\[E\d+\])?):\s*(.+)", stderr
    ):
        errors.append(
            {
                "file": m.group(1).replace("\\", "/"),
                "line": int(m.group(2)),
                "code": m.group(3),
                "message": m.group(4).strip(),
            }
        )
    return errors


def _find_owning_function(src_file: Path, err_line: int) -> str:
    """Look backwards from *err_line* to find the // [N] comment."""
    if not src_file.exists():
        return "unknown"
    src_lines = src_file.read_text(encoding="utf-8").splitlines()
    for i in range(min(err_line - 1, len(src_lines) - 1), -1, -1):
        m = re.match(r"// \[(\d+)\] (.+?) from (.+)", src_lines[i])
        if m:
            return f"{m.group(2)} ({m.group(3)})"
    return "unknown"


def map_errors_to_functions(
    errors: List[Dict], pairs: List[Dict], batch_size: int = 200
) -> Dict[str, Any]:
    """Map compiler errors back to the original Python functions."""
    error_to_functions: Dict[str, List[str]] = {}
    error_code_counts: Counter = Counter()

    for err in errors:
        file_match = re.match(r"src/batch_(\d+)\.rs", err["file"])
        if not file_match:
            continue

        func_name = _find_owning_function(CRATE_DIR / err["file"], err["line"])
        error_code_counts[err["code"]] += 1
        short_msg = err["message"][:80]
        error_to_functions.setdefault(short_msg, []).append(func_name)

    return {
        "error_code_counts": dict(error_code_counts.most_common()),
        "error_messages": {
            k: v[:3]
            for k, v in sorted(error_to_functions.items(), key=lambda x: -len(x[1]))[
                :30
            ]
        },
        "total_unique_errors": len(error_to_functions),
    }


def _print_compile_results(pairs, errors, modules, analysis):
    """Print the compilation results summary."""
    total_lines = sum(
        f.read_text(encoding="utf-8").count("\n") for f in modules if f.exists()
    )
    error_locs = len(set((e["file"], e["line"]) for e in errors))

    print(f"\n  {'=' * 60}")
    print("  COMPILATION RESULTS")
    print(f"  {'=' * 60}")
    print(f"  Total functions:  {len(pairs)}")
    print(f"  Total errors:     {len(errors)}")
    print(f"  Total Rust lines: {total_lines:,}")
    print(f"  Error locations:  {error_locs}")

    print("\n  Error code breakdown:")
    for code, count in analysis["error_code_counts"].items():
        print(f"    {code:15s}: {count:5d}")

    print(f"\n  Top error patterns ({analysis['total_unique_errors']} unique):")
    for msg, funcs in list(analysis["error_messages"].items())[:15]:
        print(f"\n    [{len(funcs)} functions] {msg}")
        for fn in funcs[:2]:
            print(f"      e.g. {fn}")
    return total_lines, error_locs


def _save_compile_report(pairs, errors, total_lines, error_locs, analysis):
    """Write compile report JSON + print cargo summary."""
    report = {
        "total_functions": len(pairs),
        "total_errors": len(errors),
        "total_lines": total_lines,
        "error_locations": error_locs,
        "error_code_counts": analysis["error_code_counts"],
        "error_messages": dict(analysis["error_messages"]),
        "raw_errors": errors[:200],
    }
    report_path = XRAY_ROOT / "_training_ground" / "compile_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Full report: {report_path}")


def main():
    print("=" * 66)
    print("  Rust Compilation Verification")
    print("=" * 66)

    print("\n  Loading transpiled pairs...")
    pairs = load_pairs()
    print(
        f"  Loaded {len(pairs)} clean pairs from "
        f"{len(set(p['project'] for p in pairs))} projects"
    )

    print("\n  Generating Cargo crate...")
    modules = generate_crate(pairs)
    print(f"  Generated {len(modules)} modules in {CRATE_DIR}")

    print("\n  Running cargo check (this may take a minute on first run)...")
    t0 = time.time()
    exit_code, stderr = run_cargo_check()
    elapsed = time.time() - t0
    print(f"  cargo check finished in {elapsed:.1f}s (exit code: {exit_code})")

    if exit_code == 0:
        print(f"\n  ALL {len(pairs)} FUNCTIONS COMPILE CLEANLY!")
        return

    errors = parse_errors(stderr)
    print(f"\n  Found {len(errors)} compilation errors")
    analysis = map_errors_to_functions(errors, pairs)
    total_lines, error_locs = _print_compile_results(pairs, errors, modules, analysis)
    _save_compile_report(pairs, errors, total_lines, error_locs, analysis)

    summary_lines = [
        ln
        for ln in stderr.strip().splitlines()
        if "error" in ln.lower() and "generated" in ln.lower()
    ]
    if summary_lines:
        print(f"\n  Cargo summary: {summary_lines[-1].strip()}")


if __name__ == "__main__":
    main()
