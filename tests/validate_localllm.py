"""Validate Rust-accelerated X_Ray on LocalLLM project."""
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
from x_ray_claude import (
    scan_codebase, DuplicateFinder, _HAS_RUST
)

print(f"Rust acceleration: {'YES' if _HAS_RUST else 'NO'}")

root = Path(r"C:\Users\Yo930\Desktop\_Python\Local_LLM")

t0 = time.perf_counter()
functions, classes, errors = scan_codebase(root)
scan_time = time.perf_counter() - t0
print(f"Scanned: {len(functions)} functions in {len(set(f.file_path for f in functions))} files ({scan_time:.2f}s)")

t1 = time.perf_counter()
finder = DuplicateFinder()
duplicates = finder.find(functions, cross_file_only=True)
dup_time = time.perf_counter() - t1
dup_summary = finder.summary()
print(f"Duplicates: {len(duplicates)} groups ({dup_time:.2f}s)")
print(f"  exact={dup_summary.get('exact_duplicates',0)} "
      f"near={dup_summary.get('near_duplicates',0)} "
      f"semantic={dup_summary.get('semantic_duplicates',0)}")

for g in duplicates[:8]:
    names = [m["name"] for m in g.functions]
    print(f"  {g.similarity_type}: {names} (avg={g.avg_similarity:.3f})")
