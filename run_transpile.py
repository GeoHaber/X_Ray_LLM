#!/usr/bin/env python3
"""Run the full transpile pipeline on Video_Transcode with Qwen2.5-Coder-14B."""
import logging
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    stream=sys.stdout,
)

from xray.transpiler import TranspileConfig, Transpiler

MODEL_PATH = r"C:\AI\Models\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"
SOURCE_DIR = r"C:\Users\dvdze\Documents\GitHub\GeorgeHaber\Video_Transcode"
OUTPUT_DIR = r"C:\Users\dvdze\Documents\GitHub\GeorgeHaber\Video_Transcode\rust_output"

config = TranspileConfig(
    output_dir=OUTPUT_DIR,
    crate_name="video_transcode",
    use_llm=True,
    llm_backend="auto",
    llm_model_path=MODEL_PATH,
    generate_tests=True,
    generate_cargo_toml=True,
    preserve_comments=True,
    type_inference=True,
    error_strategy="anyhow",
    async_runtime="tokio",
    max_llm_calls=100,
)

print(f"Transpiling: {SOURCE_DIR}")
print(f"Output:      {OUTPUT_DIR}")
print(f"Model:       {MODEL_PATH}")
print(f"Max LLM calls: {config.max_llm_calls}")
print()

t0 = time.time()
transpiler = Transpiler(config)
result = transpiler.full_pipeline(SOURCE_DIR)
elapsed = time.time() - t0

print()
print("=" * 60)
print(f"TRANSPILE COMPLETE in {elapsed:.1f}s")
print(f"  Modules transpiled: {result.modules_transpiled}")
print(f"  Files written:      {len(result.files_written)}")
print(f"  LLM calls made:     {result.llm_calls_made}")
print(f"  Compile success:    {result.compile_success}")
print(f"  Compile errors:     {len(result.compile_errors)}")
print(f"  Warnings:           {len(result.warnings)}")
if result.warnings:
    for w in result.warnings[:10]:
        print(f"    - {w}")
if result.compile_errors:
    print("\nFirst 20 error lines:")
    for e in result.compile_errors[:20]:
        print(f"  {e}")
print("=" * 60)
