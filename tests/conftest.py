
import sys
from pathlib import Path

# Add project root (one level up from tests/) to sys.path
# This ensures that "import Core.types" works regardless of CWD
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
    print(f"Added {project_root} to sys.path")
