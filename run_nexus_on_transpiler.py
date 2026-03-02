import sys
import logging
import json
from pathlib import Path

# Provide X_Ray root path
root_path = Path(__file__).parent
sys.path.insert(0, str(root_path))

from Analysis.NexusMode.orchestrator import NexusOrchestrator

logging.basicConfig(level=logging.INFO)

def main():
    orchestrator = NexusOrchestrator(root_path)
    
    transpiler_path = root_path / "Analysis" / "transpiler.py"
    if not transpiler_path.exists():
        print("Could not find transpiler.py")
        return

    print("--- 1. Building Graph for transpiler.py ---")
    orchestrator.build_context_graph([transpiler_path])
    
    print("--- 2. Running X-Ray AST Translators ---")
    res = orchestrator.run_transpilation_pipeline('x-ray')
    
    print("--- 3. Verifying Generated Rust with Cargo ---")
    verified = orchestrator.verify_and_build(res)
    
    print(f"\nResults: {len(verified)} functions passed Cargo Check out of {len(res)} attempted.")
    
    # Save the output to a file for review
    output_data = []
    for r in res:
        output_data.append({
            "function": r.get("function"),
            "status": r.get("status"),
            "rust_code": r.get("rust_code", ""),
            "cargo_error": r.get("cargo_error", "")
        })
    
    out_file = root_path / "nexus_transpiler_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)
        
    print(f"Detailed output saved to {out_file.name}")

if __name__ == "__main__":
    main()
