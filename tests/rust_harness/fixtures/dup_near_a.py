"""
Near-duplicate fixture — file A.
Contains functions that are ~75-90% textually similar to those in
dup_near_b.py. The AST structure MUST differ (so Stage 1b structural
hash doesn't match), but text similarity > 0.70 (so Stage 2 catches them).

Strategy: minimal targeted diffs — .lower() vs .upper(), one extra line,
different string constant — that break structure_hash but preserve text.
"""


def process_records(records, config=None):
    """Process a list of records and return cleaned output."""
    output = []
    for record in records:
        cleaned = record.strip()
        if cleaned and len(cleaned) > 0:
            normalized = cleaned.lower()
            output.append(normalized)
    return output


def calculate_statistics(values):
    """Calculate basic statistics for a list of values."""
    if not values:
        return {"mean": 0, "total": 0, "count": 0}
    total = sum(values)
    count = len(values)
    mean = total / count
    return {"mean": mean, "total": total, "count": count}


def build_report_header(title, author, date):
    """Build a formatted report header string."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"  Title:  {title}")
    lines.append(f"  Author: {author}")
    lines.append(f"  Date:   {date}")
    lines.append("=" * 60)
    return "\n".join(lines)
