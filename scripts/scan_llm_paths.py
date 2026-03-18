"""
Scan all GeorgeHaber projects for files that reference llama.cpp / GGUF models /
LLM binary paths — to identify what needs portable path configuration.
"""
import os
import re
from pathlib import Path

# Default: 3 levels up from scripts/ -> X_Ray_LLM/ -> GitHub/ -> GeorgeHaber/
# Override with GEORGEHABER_ROOT env var for portability across machines
BASE = Path(os.environ.get("GEORGEHABER_ROOT", "")) if os.environ.get("GEORGEHABER_ROOT") else Path(__file__).resolve().parent.parent.parent
SKIP = {
    "_OLD_JUNK", ".venv", "__pycache__", ".git", "node_modules",
    ".pytest_cache", "_bin_backup_b4392", "qdrant_storage", "rag_storage",
    "rag_cache", "conversation_cache", "dist_build", ".ruff_cache",
    ".mypy_cache", "site-packages", "target",
}
EXTS = {".py", ".bat", ".sh"}

PATTERNS = {
    "llama-server binary": re.compile(r"llama[_\-]server|LlamaServer", re.I),
    "llama-cpp library":   re.compile(r"llama[_\-]cpp|llama\.cpp", re.I),
    "GGUF model ref":      re.compile(r"\.gguf", re.I),
    "hardcoded C:\\AI\\":  re.compile(r"C:\\\\AI\\\\|C:/AI/|C:\\AI\\", re.I),
    "env vars (good)":     re.compile(r"SWARM_MODELS|ZENAI_MODEL|ZENAI_LLAMA|ZENAI_BITNET|ZENAI_BIN", re.I),
}

results = {}  # project -> list of (rel_path, set_of_matched_pattern_names)

for proj_dir in sorted(BASE.iterdir()):
    if not proj_dir.is_dir() or proj_dir.name.startswith("."):
        continue
    proj = proj_dir.name
    for root, dirs, files in os.walk(proj_dir):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for fname in files:
            if Path(fname).suffix not in EXTS:
                continue
            fpath = Path(root) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            matched = {name for name, pat in PATTERNS.items() if pat.search(text)}
            if matched:
                rel = str(fpath.relative_to(BASE))
                results.setdefault(proj, []).append((rel, matched))

print("\n" + "=" * 72)
print("  LLM / GGUF / llama.cpp Path Reference Scan")
print("=" * 72)
for proj in sorted(results):
    print(f"\n{'─'*60}")
    print(f"  PROJECT: {proj}")
    print(f"{'─'*60}")
    for rel, pats in sorted(results[proj]):
        good = "env vars (good)" in pats
        bad  = "hardcoded C:\\AI\\" in pats
        flag = "  [HARDCODED]" if bad else ("  [has env vars]" if good else "")
        print(f"  {rel}{flag}")
        for p in sorted(pats):
            if p != "env vars (good)":
                print(f"      • {p}")
print("\n" + "=" * 72)
print(f"  Total projects with LLM references: {len(results)}")
print("=" * 72)
