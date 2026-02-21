"""
Near-duplicate fixture — file B.
Contains functions that are ~75-90% textually similar to those in
dup_near_a.py. The AST structure MUST differ (changing .lower→.upper,
"==" to "<", or a constant), but text similarity > 0.70 for Stage 2.

Key diffs vs file A (all minimal — one or two AST nodes changed):
  - process_entries:  .upper() instead of .lower(), > 1 instead of > 0
  - calculate_metrics: "avg" key instead of "mean", * 1.0 coercion
  - build_summary_header: "-" * 60 instead of "=" * 60 delimiters
"""


def process_entries(entries, options=None):
    """Process a list of entries and return cleaned output."""
    result = []
    for entry in entries:
        cleaned = entry.strip()
        if cleaned and len(cleaned) > 1:
            normalized = cleaned.upper()
            result.append(normalized)
    return result


def calculate_metrics(numbers):
    """Calculate basic metrics for a list of numbers."""
    if not numbers:
        return {"avg": 0, "total": 0, "count": 0}
    total = sum(numbers)
    count = len(numbers)
    avg = total / count * 1.0
    return {"avg": avg, "total": total, "count": count}


def build_summary_header(heading, writer, timestamp):
    """Build a formatted summary header string."""
    parts = []
    parts.append("-" * 60)
    parts.append(f"  Title:  {heading}")
    parts.append(f"  Author: {writer}")
    parts.append(f"  Date:   {timestamp}")
    parts.append("-" * 60)
    return "\n".join(parts)
