import sys
from pathlib import Path

# Ensure X_Ray root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from Analysis.auto_rustify import RustifyPipeline, RustifyConfig

def main():
    print("Building rustified .exe of X-Ray...")
    
    # Configure pipeline for standalone binary
    # We set a high max_candidates and low min_score to transpile as much as possible
    config = RustifyConfig(
        crate_name="x_ray_rustified",
        mode="binary",
        max_candidates=2000,
        min_score=3.0
    )
    
    # Run pipeline on the current directory
    pipeline = RustifyPipeline(
        project_dir=".",
        output_dir="_rustified_exe_build",
        config=config
    )
    
    def on_progress(frac, msg):
        print(f"[{frac*100:3.0f}%] {msg}")

    report = pipeline.run(progress_cb=on_progress)
    
    print("\n" + "="*50)
    print("Build Report:")
    if report.compile_result and report.compile_result.success:
        print(f"SUCCESS! Binary created at: {report.compile_result.artefact_path}")
        print(f"Stats: {report.candidates_selected} functions transpiled to Rust")
        print(f"Compilation took: {report.compile_result.duration_s}s")
    else:
        print("FAILED to compile!")
        for err in report.errors:
            print(err)

if __name__ == "__main__":
    main()
