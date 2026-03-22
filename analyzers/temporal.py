"""
X-Ray LLM — Temporal coupling analysis (git co-change detection).
"""

import subprocess
from collections import Counter


def analyze_temporal_coupling(directory: str, days: int = 90) -> dict:
    """Find files that always change together (temporal coupling from git)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days}.days", "--name-only", "--pretty=format:---COMMIT---"],
            capture_output=True,
            text=True,
            cwd=directory,
            timeout=30,
        )
    except FileNotFoundError:
        return {"error": "git not found."}
    except subprocess.TimeoutExpired:
        return {"error": "git log timed out."}

    if result.returncode != 0:
        return {"error": f"git error: {result.stderr.strip()[:200]}"}

    # Parse commits
    commits = []
    current_files = []
    for line in result.stdout.split("\n"):
        line = line.strip()
        if line == "---COMMIT---":
            if current_files:
                commits.append(set(current_files))
            current_files = []
        elif line:
            current_files.append(line)
    if current_files:
        commits.append(set(current_files))

    # Count co-changes
    pairs = Counter()
    for files in commits:
        flist = sorted(files)
        for i in range(len(flist)):
            for j in range(i + 1, len(flist)):
                pairs[(flist[i], flist[j])] += 1

    # Filter to significant pairs (>= 3 co-changes)
    couplings = []
    for (a, b), count in pairs.most_common(100):
        if count < 3:
            break
        couplings.append(
            {
                "file_a": a,
                "file_b": b,
                "co_changes": count,
                "strength": round(count / len(commits) * 100, 1) if commits else 0,
            }
        )

    return {
        "couplings": couplings,
        "total_commits": len(commits),
        "total_pairs": len(couplings),
    }
