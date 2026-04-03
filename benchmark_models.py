#!/usr/bin/env python3
"""Benchmark all available GGUF models for Rust compile error fixing.

Tests speed, accuracy, and code quality across multiple error scenarios.
"""
import json
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Force unbuffered output
import functools

print = functools.partial(print, flush=True)

from pathlib import Path

MODEL_DIR = Path(r"C:\AI\Models")
BIN_DIR = Path(r"C:\AI\_bin")
PORT = 8095

# ── Test cases: real Rust compile errors from Video_Transcode transpile ──

TEST_CASES = [
    {
        "name": "E0308 type mismatch (vec len to string)",
        "error": "E0308 -> mismatched types: expected `String`, found `usize`",
        "file": "utils.rs",
        "line": 42,
        "context": '''\
   0038 | fn count_items(items: &Vec<String>) -> String {
   0039 |     let mut result = String::new();
   0040 |     for item in items {
   0041 |         result.push_str(item);
>>>0042 |     }
   0043 |     items.len()
   0044 | }''',
        "expected_fix": "to_string",  # Should use .to_string() or format!
    },
    {
        "name": "E0433 unresolved module (os.path)",
        "error": "E0433 -> failed to resolve: use of unresolved module `os`",
        "file": "config.rs",
        "line": 5,
        "context": '''\
   0001 | use std::collections::HashMap;
   0002 | use anyhow::Result;
   0003 |
   0004 | fn get_config_path() -> String {
>>>0005 |     let home = os::env::var("HOME").unwrap_or_default();
   0006 |     let path = os::path::join(&home, ".config");
   0007 |     path
   0008 | }''',
        "expected_fix": "std::env",  # Should use std::env::var
    },
    {
        "name": "E0599 PathBuf Display",
        "error": "E0599 -> `PathBuf` doesn't implement `std::fmt::Display`",
        "file": "ffmpeg.rs",
        "line": 15,
        "context": '''\
   0011 | use std::path::PathBuf;
   0012 |
   0013 | fn log_path(path: &PathBuf) {
   0014 |     println!("Processing file: {}", path);
>>>0015 | }
   0016 |
   0017 | fn get_extension(path: &PathBuf) -> String {
   0018 |     path.extension().unwrap().to_string()''',
        "expected_fix": "display",  # Should use path.display()
    },
    {
        "name": "E0369 PathBuf division (path join)",
        "error": "E0369 -> cannot divide `PathBuf` by `String`",
        "file": "transcode.rs",
        "line": 22,
        "context": '''\
   0018 | use std::path::PathBuf;
   0019 |
   0020 | fn build_output_path(base_dir: &PathBuf, filename: &str) -> PathBuf {
   0021 |     let output_dir = base_dir / "output";
>>>0022 |     let full_path = output_dir / filename;
   0023 |     full_path
   0024 | }''',
        "expected_fix": "join",  # Should use .join()
    },
    {
        "name": "E0425 Python test mock (MagicMock)",
        "error": "E0425 -> cannot find function `MagicMock` in this scope",
        "file": "test_ffmpeg.rs",
        "line": 8,
        "context": '''\
   0004 | #[cfg(test)]
   0005 | mod tests {
   0006 |     use super::*;
   0007 |
>>>0008 |     let mock_process = MagicMock();
   0009 |     mock_process.returncode = 0;
   0010 |     mock_process.stdout = b"output";
   0011 |
   0012 |     fn test_run_ffmpeg() {''',
        "expected_fix": "struct",  # Should create a mock struct or use mockall
    },
]

# Models to test (must have .gguf in MODEL_DIR)
MODELS_TO_TEST = [
    ("Qwen2.5-Coder-14B", "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"),
    ("Qwen3.5-9B", "Qwen3.5-9B-Q4_K_M.gguf"),
    ("Devstral-Small-24B", "Devstral-Small-2-24B-Q4_K_M.gguf"),
    ("Gemma-4-E4B", "gemma-4-E4B-it-Q4_K_M.gguf"),
    ("GLM-4.7-Flash", "glm-4.7-flash-32b-q4_k_m.gguf"),
    ("DeepSeek-R1-14B", "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf"),
    ("gpt-oss-20b", "gpt-oss-20B-Q4_K_M.gguf"),
]


def start_server(model_path: str, timeout: int = 180) -> bool:
    """Start llama-server with the given model. Returns True if healthy."""
    import subprocess
    global _server_proc
    cmd = [
        str(BIN_DIR / "llama-server.exe"),
        "--model", model_path,
        "--port", str(PORT),
        "--ctx-size", "4096",
        "--n-gpu-layers", "-1",
        "--host", "0.0.0.0",
        "--flash-attn", "on",
    ]
    _server_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Wait for health
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_proc.poll() is not None:
            return False
        try:
            r = requests.get(f"http://localhost:{PORT}/health", timeout=2)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def stop_server():
    global _server_proc
    if _server_proc:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=10)
        except Exception:
            _server_proc.kill()
        _server_proc = None


def generate(prompt: str, max_tokens: int = 512) -> tuple[str, float]:
    """Send prompt and return (response, elapsed_seconds)."""
    import requests
    t0 = time.time()
    resp = requests.post(
        f"http://localhost:{PORT}/v1/chat/completions",
        json={
            "model": "local",
            "messages": [
                {"role": "system", "content": "You are a Rust compiler error fixer. Return ONLY corrected code lines, no explanations, no markdown fences."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        },
        timeout=120,
    )
    elapsed = time.time() - t0
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return content, elapsed


def build_prompt(tc: dict) -> str:
    return (
        f"Fix this Rust compilation error. Return ONLY the corrected lines, "
        f"no explanations, no markdown fences.\n\n"
        f"Error: {tc['error']}\n"
        f"File: {tc['file']}, line {tc['line']}\n\n"
        f"Code context:\n{tc['context']}\n\n"
        f"The line marked with >>> has the error. "
        f"Return ONLY the fixed version of the code (corrected lines):"
    )


def score_response(response: str, tc: dict) -> dict:
    """Score a response for accuracy and quality."""
    resp_lower = response.lower()
    expected = tc["expected_fix"].lower()

    # Accuracy: does it contain the expected fix pattern?
    accurate = expected in resp_lower

    # Code quality checks
    has_explanation = any(w in resp_lower for w in ["the error", "the issue", "the problem", "because", "note:"])
    has_markdown = "```" in response
    is_code_only = not has_explanation and not has_markdown
    is_concise = len(response.strip().splitlines()) <= 15

    return {
        "accurate": accurate,
        "code_only": is_code_only,
        "concise": is_concise,
        "response_length": len(response),
        "line_count": len(response.strip().splitlines()),
    }


_server_proc = None


def main():
    print("=" * 70)
    print("MODEL BENCHMARK: Rust Compile Error Fixing")
    print(f"Models dir: {MODEL_DIR}")
    print(f"Test cases: {len(TEST_CASES)}")
    print("=" * 70)
    print()

    # Filter to models that exist
    available = []
    for name, filename in MODELS_TO_TEST:
        path = MODEL_DIR / filename
        if path.exists():
            size_gb = path.stat().st_size / (1024**3)
            available.append((name, str(path), size_gb))
            print(f"  [OK] {name} ({size_gb:.1f} GB)")
        else:
            print(f"  [--] {name} (not found: {filename})")
    print()

    if not available:
        print("No models found!")
        return

    results = {}

    for model_name, model_path, size_gb in available:
        print(f"\n{'='*70}")
        print(f"TESTING: {model_name} ({size_gb:.1f} GB)")
        print(f"{'='*70}")

        # Start server
        print("  Starting server...")
        t_start = time.time()
        healthy = start_server(model_path)
        load_time = time.time() - t_start

        if not healthy:
            print("  FAILED to start in 180s. Skipping.")
            stop_server()
            results[model_name] = {"status": "FAILED_TO_START", "load_time": load_time}
            continue

        print(f"  Server ready in {load_time:.1f}s")

        model_results = {
            "load_time": load_time,
            "size_gb": size_gb,
            "tests": [],
        }

        total_time = 0
        correct = 0
        code_only_count = 0

        for i, tc in enumerate(TEST_CASES):
            prompt = build_prompt(tc)
            try:
                response, elapsed = generate(prompt)
                scores = score_response(response, tc)
                total_time += elapsed

                if scores["accurate"]:
                    correct += 1
                if scores["code_only"]:
                    code_only_count += 1

                status = "PASS" if scores["accurate"] else "FAIL"
                print(f"  [{status}] {tc['name']}: {elapsed:.1f}s, {scores['line_count']} lines")
                if not scores["accurate"]:
                    # Show first 3 lines of response for debugging
                    preview = "\n".join(response.strip().splitlines()[:3])
                    print(f"        Response preview: {preview[:120]}")

                model_results["tests"].append({
                    "name": tc["name"],
                    "accurate": scores["accurate"],
                    "elapsed": elapsed,
                    "code_only": scores["code_only"],
                    "concise": scores["concise"],
                    "line_count": scores["line_count"],
                })
            except Exception as exc:
                print(f"  [ERR] {tc['name']}: {exc}")
                model_results["tests"].append({
                    "name": tc["name"],
                    "accurate": False,
                    "elapsed": 0,
                    "error": str(exc),
                })

        model_results["total_time"] = total_time
        model_results["accuracy"] = correct / len(TEST_CASES) * 100
        model_results["correct"] = correct
        model_results["code_only_pct"] = code_only_count / len(TEST_CASES) * 100
        model_results["avg_time"] = total_time / len(TEST_CASES) if TEST_CASES else 0

        print(f"\n  SUMMARY: {correct}/{len(TEST_CASES)} correct ({model_results['accuracy']:.0f}%), "
              f"avg {model_results['avg_time']:.1f}s/fix, total {total_time:.1f}s")

        results[model_name] = model_results
        stop_server()
        time.sleep(2)  # Cool down between models

    # ── Final comparison ──
    print(f"\n\n{'='*70}")
    print("FINAL COMPARISON")
    print(f"{'='*70}\n")

    # Header
    print(f"{'Model':<22} {'Size':>6} {'Accuracy':>10} {'Avg Time':>10} {'Total':>8} {'Code-Only':>10} {'Load':>6}")
    print("-" * 80)

    # Sort by accuracy then speed
    ranked = sorted(
        [(name, r) for name, r in results.items() if "accuracy" in r],
        key=lambda x: (-x[1]["accuracy"], x[1]["avg_time"]),
    )

    for i, (name, r) in enumerate(ranked):
        medal = [">>", "  ", "  ", "  ", "  ", "  ", "  "][min(i, 6)]
        print(f"{medal}{name:<20} {r['size_gb']:>5.1f}G {r['accuracy']:>9.0f}% "
              f"{r['avg_time']:>9.1f}s {r['total_time']:>7.1f}s "
              f"{r['code_only_pct']:>9.0f}% {r['load_time']:>5.1f}s")

    # Failed models
    failed = [(name, r) for name, r in results.items() if "accuracy" not in r]
    for name, r in failed:
        print(f"  {name:<20} {'FAILED':>6} {'--':>10} {'--':>10} {'--':>8} {'--':>10} {r.get('load_time', 0):>5.1f}s")

    print()

    # Winner
    if ranked:
        winner = ranked[0]
        print(f"WINNER: {winner[0]} -> {winner[1]['accuracy']:.0f}% accuracy, {winner[1]['avg_time']:.1f}s avg")

    # Save results
    results_path = Path(__file__).parent / "benchmark_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")


if __name__ == "__main__":
    main()
