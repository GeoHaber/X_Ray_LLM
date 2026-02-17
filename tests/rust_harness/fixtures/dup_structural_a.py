"""
Structural duplicate fixture — file A.
Contains functions with identical AST structure but completely different
variable names. Should be caught by Stage 1b (ASTNormalizer + structure_hash).
"""


def transform_items(collection, threshold):
    """Transform items above threshold."""
    results = []
    for item in collection:
        if item > threshold:
            processed = item * 2
            results.append(processed)
        else:
            results.append(item)
    return results


def merge_datasets(primary, secondary, key_field):
    """Merge two datasets on a key field."""
    merged = {}
    for record in primary:
        k = record.get(key_field)
        if k is not None:
            merged[k] = record
    for record in secondary:
        k = record.get(key_field)
        if k is not None:
            if k in merged:
                merged[k].update(record)
            else:
                merged[k] = record
    return list(merged.values())
