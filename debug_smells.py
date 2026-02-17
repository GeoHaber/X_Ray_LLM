
from Core.types import FunctionRecord
from Core.config import SMELL_THRESHOLDS
from Analysis.smells import CodeSmellDetector

def _func(size_lines):
    return FunctionRecord(
        name="foo", file_path="test.py",
        line_start=1, line_end=size_lines, size_lines=size_lines,
        parameters=[], return_type=None, decorators=[],
        docstring="Doc", calls_to=[], complexity=1,
        nesting_depth=0, code_hash="h", structure_hash="s",
        code="pass", is_async=False
    )

def debug_smells():
    t = SMELL_THRESHOLDS["very_long_function"]
    print(f"Threshold: {t}")
    f = _func(size_lines=t)
    det = CodeSmellDetector()
    det.check([f], [])
    
    print(f"Smells found: {len(det.smells)}")
    for s in det.smells:
        print(f"  {s.category}: {s.severity}")

if __name__ == "__main__":
    debug_smells()
