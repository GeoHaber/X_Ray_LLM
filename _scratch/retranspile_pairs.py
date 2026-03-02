"""
retranspile_pairs.py — Re-run transpiler on existing pairs.jsonl
================================================================
Reads pairs.jsonl, re-transpiles each Python function with the latest
transpiler, and writes updated pairs.jsonl.  Much faster than re-scanning
all projects from scratch.
"""
import sys, json, time
from pathlib import Path

XRAY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(XRAY_ROOT))

from Analysis.transpiler import transpile_function_code

PAIRS_FILE = XRAY_ROOT / "_training_ground" / "transpiled" / "pairs.jsonl"
BACKUP_FILE = PAIRS_FILE.with_suffix(".jsonl.bak")

def main():
    print("Loading pairs...")
    pairs = []
    with open(PAIRS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            pairs.append(json.loads(line))
    print(f"  {len(pairs)} pairs loaded")

    # Backup
    import shutil
    shutil.copy2(PAIRS_FILE, BACKUP_FILE)
    print(f"  Backup saved to {BACKUP_FILE.name}")

    updated = 0
    errors = 0
    t0 = time.time()

    for i, pair in enumerate(pairs):
        py_code = pair.get("python_code", "")
        if not py_code:
            continue
        try:
            new_rust = transpile_function_code(py_code)
            if new_rust != pair.get("rust_code", ""):
                updated += 1
            # Recompute metadata
            todo_count = new_rust.count("todo!()") + new_rust.count("todo!(\"")
            rust_lines = new_rust.count("\n") + 1
            clean = (
                "todo!()" not in new_rust
                and "/* " not in new_rust
                and "// TODO" not in new_rust
            )
            pair["rust_code"] = new_rust
            pair["rust_lines"] = rust_lines
            pair["todo_count"] = todo_count
            pair["clean"] = clean
        except Exception as e:
            errors += 1
            pair["rust_code"] = f"// TRANSPILE ERROR: {e}"
            pair["clean"] = False

        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(pairs)} ({elapsed:.1f}s) — {updated} changed, {errors} errors")

    elapsed = time.time() - t0
    print(f"\n  Re-transpiled {len(pairs)} functions in {elapsed:.1f}s")
    print(f"  {updated} changed, {errors} errors")

    # Count clean
    clean_count = sum(1 for p in pairs if p.get("clean"))
    print(f"  {clean_count} clean / {len(pairs)} total ({100*clean_count/len(pairs):.1f}%)")

    # Write back
    with open(PAIRS_FILE, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"  Written to {PAIRS_FILE}")

if __name__ == "__main__":
    main()
