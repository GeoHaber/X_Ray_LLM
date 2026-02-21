#!/usr/bin/env python3
"""Run library advisor analysis on RAG_RAT."""

import sys
import json
from pathlib import Path

sys.path.insert(0, ".")
from Analysis.ast_utils import collect_py_files, extract_functions_from_file
from Analysis.duplicates import DuplicateFinder
from Analysis.library_advisor import LibraryAdvisor

# Default to a sibling project; override via CLI arg if needed
_default = Path(__file__).resolve().parent.parent / "Projects" / "RAG_RAT"
root = Path(sys.argv[1]) if len(sys.argv) > 1 else _default
if not root.exists():
    print(f"Target not found: {root}  — pass a path as argument.")
    sys.exit(1)
py_files = collect_py_files(root)

all_functions = []
all_classes = []
for f in py_files:
    funcs, clses, err = extract_functions_from_file(f, root)
    all_functions.extend(funcs)
    all_classes.extend(clses)

substantial = [f for f in all_functions if f.size_lines >= 5]
finder = DuplicateFinder()
groups = finder.find(substantial)

# Library Advisor
advisor = LibraryAdvisor()
suggestions = advisor.analyze(groups, all_functions)
lib_summary = advisor.summary()

print("=== LIBRARY EXTRACTION SUGGESTIONS ===")
print(json.dumps(lib_summary, indent=2))
print()

# Print top suggestions
for s in suggestions[:20]:
    desc = s.description
    mod = s.module_name
    print(f"Module: {mod} | {desc}")
    for func in s.functions[:3]:
        fname = func.get("file", "?")
        fline = func.get("line", "")
        fnam = func.get("name", "?")
        print(f"  - {fname}:{fline} ({fnam})")
    if len(s.functions) > 3:
        print(f"  ... and {len(s.functions) - 3} more")
    print()

# Also get detailed duplicate info
print("\n=== TOP DUPLICATE GROUPS (by similarity) ===")
sorted_groups = sorted(groups, key=lambda g: g.avg_similarity, reverse=True)
for g in sorted_groups[:30]:
    print(f"\nGroup {g.group_id} ({g.similarity_type}, avg={g.avg_similarity:.2f}):")
    for func in g.functions:
        print(
            f"  {func.get('file', '?')}:{func.get('line', '')} -> {func.get('name', '?')}"
        )

# Save everything
report = {
    "library_suggestions": lib_summary,
    "duplicate_summary": finder.summary(),
    "top_groups": [
        {
            "group_id": g.group_id,
            "type": g.similarity_type,
            "similarity": g.avg_similarity,
            "functions": g.functions,
        }
        for g in sorted_groups[:50]
    ],
}
with open("rag_rat_full_analysis.json", "w") as f:
    json.dump(report, f, indent=2, default=str)
print("\nSaved full analysis to rag_rat_full_analysis.json")
