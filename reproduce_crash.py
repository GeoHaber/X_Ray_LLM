
import sys
import traceback
from pathlib import Path
import os

# Ensure X_Ray is in path
sys.path.append(os.getcwd())

try:
    from Analysis.ast_utils import extract_functions_from_file
except ImportError:
    print("Could not import Analysis.ast_utils")
    sys.exit(1)

def generate_garbage():
    return "def foo(:\n  return bar"

def reproduce():
    root = Path.cwd()
    fpath = root / "temp_garbage.py"
    fpath.write_text(generate_garbage(), encoding="utf-8")
    
    print(f"File created: {fpath}")
    
    try:
        print("Calling extract_functions_from_file...")
        funcs, classes, error = extract_functions_from_file(fpath, root)
        print(f"Result: error={error}")
    except Exception:
        print("CRASHED!")
        traceback.print_exc()
    finally:
        if fpath.exists():
            try:
                fpath.unlink()
            except OSError:
                pass

if __name__ == "__main__":
    reproduce()
