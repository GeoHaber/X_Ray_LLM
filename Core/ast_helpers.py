"""
Shared AST utility functions used across Analysis/ and Lang/ modules.
Single source of truth for AST nesting depth and complexity calculations.
"""

import ast


def compute_nesting_depth(node: ast.AST) -> int:
    """
    Compute maximum nesting depth of control flow in a function.
    
    Counts levels of: If, For, While, Try, With, ExceptHandler statements.
    """
    max_depth = 0

    def _walk(n, depth):
        nonlocal max_depth
        nesting_types = (ast.If, ast.For, ast.While, ast.Try, ast.With,
                         ast.ExceptHandler)
        for child in ast.iter_child_nodes(n):
            if isinstance(child, nesting_types):
                new_depth = depth + 1
                max_depth = max(max_depth, new_depth)
                _walk(child, new_depth)
            else:
                _walk(child, depth)

    _walk(node, 0)
    return max_depth


def compute_complexity(node: ast.AST) -> int:
    """
    Approximate cyclomatic complexity of an AST node.
    
    Counts: If, For, While, Try, ExceptHandler, BoolOp, Assert, comprehension.
    """
    return sum(
        1 for c in ast.walk(node)
        if isinstance(c, (ast.If, ast.For, ast.While, ast.Try,
                          ast.ExceptHandler, ast.BoolOp, ast.Assert,
                          ast.comprehension))
    )
