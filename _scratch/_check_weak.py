import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Analysis.transpiler import transpile_function_code

print("=== walrus ===")
print(transpile_function_code('def check(items):\n    if (n := len(items)) > 10:\n        return n'))

print("\n=== match/case ===")
code = '''def classify(x: int) -> str:
    match x:
        case 0: return "zero"
        case _: return "other"'''
print(transpile_function_code(code))

print("\n=== yield ===")
print(transpile_function_code('def gen(n: int):\n    for i in range(n):\n        yield i'))
