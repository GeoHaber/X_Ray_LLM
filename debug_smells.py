from Core.config import SMELL_THRESHOLDS
from Analysis.smells import CodeSmellDetector
from tests.conftest import make_func


def debug_smells():
    t = SMELL_THRESHOLDS["very_long_function"]
    print(f"Threshold: {t}")
    f = make_func(size_lines=t)
    det = CodeSmellDetector()
    det.check([f], [])

    print(f"Smells found: {len(det.smells)}")
    for s in det.smells:
        print(f"  {s.category}: {s.severity}")


if __name__ == "__main__":
    debug_smells()
