"""Find all critical code smells in the ZEN_AI_RAG project."""
import ast, os, glob

os.chdir(r"C:\Users\Yo930\Desktop\_Python\Projects\ZEN_AI_RAG")

all_crits = []


def get_max_nesting(node):
    """Get max nesting depth of a function."""
    result = [0]
    def walk(n, depth):
        if isinstance(n, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
            depth += 1
            result[0] = max(result[0], depth)
        for child in ast.iter_child_nodes(n):
            walk(child, depth)
    walk(node, 0)
    return result[0]


def get_cc(node):
    """Get cyclomatic complexity of a function."""
    cc = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.IfExp)):
            cc += 1
        elif isinstance(n, (ast.For, ast.While)):
            cc += 1
        elif isinstance(n, ast.ExceptHandler):
            cc += 1
        elif isinstance(n, ast.BoolOp):
            cc += len(n.values) - 1
    return cc


def check_node(node, pyfile):
    """Check a single AST node for critical smells."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lines = (node.end_lineno or node.lineno) - node.lineno + 1
        max_d = get_max_nesting(node)
        cc = get_cc(node)
        if lines >= 120:
            all_crits.append((pyfile, node.name, "long", lines, node.lineno))
        if max_d >= 6:
            all_crits.append((pyfile, node.name, "nesting", max_d, node.lineno))
        if cc >= 20:
            all_crits.append((pyfile, node.name, "complex", cc, node.lineno))
    elif isinstance(node, ast.ClassDef):
        methods = sum(1 for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        if methods >= 15:
            all_crits.append((pyfile, node.name, "god-class", methods, node.lineno))
        # Also check methods inside the class
        for n in node.body:
            check_node(n, pyfile)


for pyfile in glob.glob("**/*.py", recursive=True):
    if "__pycache__" in pyfile or ".venv" in pyfile:
        continue
    try:
        with open(pyfile, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception:
        continue
    for node in tree.body:
        check_node(node, pyfile)

print(f"Total criticals found: {len(all_crits)}")
print()
from collections import Counter

by_file = Counter(c[0] for c in all_crits)
print("Criticals by file:")
for f, cnt in by_file.most_common(30):
    print(f"  {cnt:3d} {f}")
print()
print("All critical items:")
for f, name, kind, val, line in sorted(all_crits, key=lambda x: x[0]):
    print(f"  {f}:L{line} {name} ({kind}={val})")
