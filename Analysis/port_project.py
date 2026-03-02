import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Analysis.auto_rustify import transpile_module

PROJECT_ROOT = Path(__file__).parent.parent
RUST_ROOT = PROJECT_ROOT / "X_Ray_Rust_Full"
SRC_DIR = RUST_ROOT / "src"

FILES_TO_PORT = [
    "Core/types.py",
    # "Core/utils.py", # Might be complex with logging
    # "Analysis/duplicates.py" # Complex
]


def run_port():
    print(f"Porting files to {SRC_DIR}...")
    SRC_DIR.mkdir(parents=True, exist_ok=True)

    # Create lib.rs content
    lib_rs_lines = ["use pyo3::prelude::*;", ""]

    for rel_path in FILES_TO_PORT:
        py_path = PROJECT_ROOT / rel_path
        if not py_path.exists():
            print(f"Skipping {rel_path} (not found)")
            continue

        print(f"Transpiling {rel_path}...")
        code = py_path.read_text(encoding="utf-8")
        rust_code = transpile_module(code, pyo3=True)

        # Determine module name
        name = py_path.stem
        if name == "types":
            name = "types_rs"  # Avoid keyword conflict or confusion

        rust_path = SRC_DIR / f"{name}.rs"
        rust_path.write_text(rust_code, encoding="utf-8")

        lib_rs_lines.append(f"pub mod {name};")

    # Finalize lib.rs
    lib_rs_lines.append("")
    lib_rs_lines.append("#[pymodule]")
    lib_rs_lines.append(
        "fn x_ray_rust_full(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {"
    )
    for rel_path in FILES_TO_PORT:
        name = Path(rel_path).stem
        if name == "types":
            name = "types_rs"
        # We need to expose classes/fns from submodules?
        # For now, just let them be regular mods.
        pass
    lib_rs_lines.append("    Ok(())")
    lib_rs_lines.append("}")

    (SRC_DIR / "lib.rs").write_text("\n".join(lib_rs_lines), encoding="utf-8")
    print("Porting complete.")


if __name__ == "__main__":
    run_port()
