"""
Structural duplicate fixture — file B.
Same AST structure as dup_structural_a.py but different variable names.
Should be caught by Stage 1b (ASTNormalizer + structure_hash).
"""


def filter_entries(data_list, cutoff):
    """Filter entries above cutoff."""
    output = []
    for entry in data_list:
        if entry > cutoff:
            modified = entry * 2
            output.append(modified)
        else:
            output.append(entry)
    return output


def combine_sources(base, overlay, join_key):
    """Combine two sources on a join key."""
    combined = {}
    for row in base:
        k = row.get(join_key)
        if k is not None:
            combined[k] = row
    for row in overlay:
        k = row.get(join_key)
        if k is not None:
            if k in combined:
                combined[k].update(row)
            else:
                combined[k] = row
    return list(combined.values())
