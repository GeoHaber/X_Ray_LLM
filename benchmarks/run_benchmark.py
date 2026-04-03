#!/usr/bin/env python3
"""
LLM Model Benchmark for Rust Compile Error Fixing
===================================================

Evaluates local GGUF models on their ability to fix Rust compilation errors,
measuring speed, accuracy, and code quality. Designed for comparing models
used in the X-Ray LLM Python-to-Rust transpiler.

Usage:
    # Run full benchmark with all available models
    python benchmarks/run_benchmark.py

    # Test specific models only
    python benchmarks/run_benchmark.py --models "Qwen2.5-Coder-14B,Gemma-4-E4B"

    # Use custom test cases
    python benchmarks/run_benchmark.py --test-cases path/to/cases.json

    # Adjust settings
    python benchmarks/run_benchmark.py --port 8095 --timeout 180 --ctx-size 8192

    # Warmup prompt before benchmarking (reduces cold-start variance)
    python benchmarks/run_benchmark.py --warmup

Output:
    - Console table with speed/accuracy/quality comparison
    - benchmarks/results/<timestamp>_results.json with full details
    - Each model gets a score (0-100) combining accuracy, speed, and quality

Test Cases:
    Loaded from benchmarks/test_cases.json (editable).
    Each case has:
      - error_code: Rust error code (E0308, E0433, etc.)
      - context: Source code with the error line marked >>>
      - expected_patterns: strings that should appear in a correct fix
      - anti_patterns: strings that indicate a wrong fix
      - difficulty: easy/medium/hard (affects scoring weight)

Adding New Test Cases:
    Edit benchmarks/test_cases.json and add entries following the schema.
    Run with --validate to check test case format without running models.

Adding New Models:
    Edit the MODELS dict in this file or pass --models-dir to scan a directory.
"""
import argparse
import functools
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
print = functools.partial(print, flush=True)

# ── Model Registry ───────────────────────────────────────────────────────
# Maps display name -> GGUF filename. Add new models here.

MODELS: dict[str, str] = {
    "Qwen2.5-Coder-14B":   "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
    "Qwen3.5-9B":          "Qwen3.5-9B-Q4_K_M.gguf",
    "Devstral-Small-24B":  "Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf",
    "Gemma-4-E4B":         "gemma-4-E4B-it-Q4_K_M.gguf",
    "GLM-4.7-Flash":       "GLM-4.7-Flash-Q4_K_M.gguf",
    "DeepSeek-R1-14B":     "DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf",
    "gpt-oss-20b":         "gpt-oss-20b-MXFP4.gguf",
    "Qwen2.5-14B":         "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
    "Qwen2.5-Coder-7B":    "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    "DeepSeek-Coder-6.7B":  "deepseek-coder-6.7b-instruct.Q4_K_M.gguf",
    "Gemma-2-9B":          "gemma-2-9b-it-Q4_K_M.gguf",
    "Phi-3.5-Mini":        "Phi-3.5-mini-instruct-Q4_K_M.gguf",
    "Llama-3.2-3B":        "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    "Mistral-7B":          "Mistral-7B-Instruct-v0.3.Q4_K_M.gguf",
}

# Difficulty weights for scoring
DIFFICULTY_WEIGHT = {"easy": 1.0, "medium": 1.5, "hard": 2.0}

# ── Environment Variables ────────────────────────────────────────────────
# ZENAI_LLAMA_SERVER  - Path to llama-server binary
# SWARM_MODELS_DIR    - Directory containing GGUF model files
# ZENAI_MODEL_PATH    - Default model path (optional)

DEFAULT_MODELS_DIR = os.environ.get("SWARM_MODELS_DIR", r"C:\AI\Models")


# ── Hardware Detection ───────────────────────────────────────────────────

def detect_hardware() -> dict:
    """Detect CPU, GPU, and NPU hardware info."""
    hw = {"cpu": "unknown", "gpu": "unknown", "npu": "unknown", "os": platform.platform()}

    # CPU info
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors", "/format:list"],
                text=True, timeout=10,
            )
            for line in out.strip().splitlines():
                if line.startswith("Name="):
                    hw["cpu"] = line.split("=", 1)[1].strip()
                elif line.startswith("NumberOfCores="):
                    hw["cpu_cores"] = int(line.split("=", 1)[1].strip())
                elif line.startswith("NumberOfLogicalProcessors="):
                    hw["cpu_threads"] = int(line.split("=", 1)[1].strip())
        except Exception:
            pass

        # GPU info (AMD/NVIDIA/Intel)
        try:
            out = subprocess.check_output(
                ["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM", "/format:list"],
                text=True, timeout=10,
            )
            gpus = []
            current = {}
            for line in out.strip().splitlines():
                if line.startswith("Name="):
                    current["name"] = line.split("=", 1)[1].strip()
                elif line.startswith("AdapterRAM="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        current["vram_bytes"] = int(val)
                if "name" in current and "vram_bytes" in current:
                    gpus.append(current)
                    current = {}
            if current.get("name"):
                gpus.append(current)
            if gpus:
                hw["gpu"] = gpus[0]["name"]
                hw["gpu_all"] = gpus
        except Exception:
            pass

        # NPU detection (AMD XDNA / Intel NPU)
        try:
            out = subprocess.check_output(
                ["wmic", "path", "Win32_PnPEntity", "where",
                 "Name like '%NPU%' or Name like '%Neural%' or Name like '%XDNA%' or Name like '%IPU%'",
                 "get", "Name", "/format:list"],
                text=True, timeout=10,
            )
            npus = [l.split("=", 1)[1].strip() for l in out.strip().splitlines() if l.startswith("Name=")]
            if npus:
                hw["npu"] = npus[0]
        except Exception:
            pass
    else:
        # Linux fallback
        try:
            hw["cpu"] = subprocess.check_output(
                ["grep", "-m1", "model name", "/proc/cpuinfo"], text=True, timeout=5
            ).split(":", 1)[1].strip()
        except Exception:
            pass

    # CPU feature flags (AVX512, AVX2, etc.)
    if os.name == "nt":
        try:
            # Check via llama-server --version or env
            cpu_name = hw.get("cpu", "").lower()
            features = []
            if "zen 4" in cpu_name or "zen4" in cpu_name or "7840" in cpu_name or "7940" in cpu_name or "9" in cpu_name:
                features.extend(["AVX512", "AVX2", "FMA"])
            elif "zen 3" in cpu_name or "zen3" in cpu_name:
                features.extend(["AVX2", "FMA"])
            hw["cpu_features"] = features
        except Exception:
            pass

    return hw


# ── Server Management ────────────────────────────────────────────────────

# Backend options for llama-server
BACKENDS = {
    "cpu":    [],                                # Default CPU backend
    "vulkan": ["--n-gpu-layers", "-1"],          # Vulkan GPU offload (AMD/NVIDIA/Intel)
    "auto":   ["--n-gpu-layers", "-1"],          # Let llama.cpp decide
}

_server_proc = None


def find_llama_server() -> str:
    """Find llama-server binary using env vars and common paths."""
    candidates = [
        os.environ.get("ZENAI_LLAMA_SERVER", ""),
        os.environ.get("LLAMA_SERVER_BIN", ""),
        shutil.which("llama-server") or "",
        str(Path.home() / "AI" / "_bin" / ("llama-server.exe" if os.name == "nt" else "llama-server")),
        str(Path("C:/AI/_bin/llama-server.exe")) if os.name == "nt" else "",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    raise FileNotFoundError(
        "llama-server not found. Set ZENAI_LLAMA_SERVER or LLAMA_SERVER_BIN env var, "
        "or install to C:\\AI\\_bin\\llama-server.exe"
    )


def start_server(model_path: str, port: int, ctx_size: int, timeout: int,
                  backend: str = "auto") -> float:
    """Start llama-server. Returns load time in seconds. Raises on failure."""
    global _server_proc
    binary = find_llama_server()
    cmd = [
        binary,
        "--model", model_path,
        "--port", str(port),
        "--ctx-size", str(ctx_size),
        "--host", "127.0.0.1",
        "--flash-attn", "on",
    ]
    # Add backend-specific flags
    backend_flags = BACKENDS.get(backend, BACKENDS["auto"])
    cmd.extend(backend_flags)
    t0 = time.time()
    _server_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_proc.poll() is not None:
            raise RuntimeError(f"llama-server exited with rc={_server_proc.returncode}")
        try:
            r = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return time.time() - t0
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"llama-server did not become healthy within {timeout}s")


def stop_server():
    """Stop the running llama-server."""
    global _server_proc
    if _server_proc:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=10)
        except Exception:
            _server_proc.kill()
        _server_proc = None


def warmup_server(port: int):
    """Send a warmup prompt to reduce cold-start variance."""
    import requests
    try:
        requests.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json={
                "model": "local",
                "messages": [{"role": "user", "content": "Say hello."}],
                "max_tokens": 5,
            },
            timeout=60,
        )
    except Exception:
        pass


# ── LLM Generation ──────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a Rust compiler error fixer. "
    "Return ONLY the corrected code lines, no explanations, "
    "no markdown fences, no commentary."
)

_direct_llm = None  # In-process llama_cpp.Llama instance


def generate(port: int, prompt: str, max_tokens: int = 512) -> tuple[str, float, dict]:
    """Send prompt to LLM. Returns (response, elapsed_s, usage).

    Uses in-process llama_cpp if _direct_llm is set, else HTTP to llama-server.
    """
    if _direct_llm is not None:
        return _generate_direct(prompt, max_tokens)

    import requests
    t0 = time.time()
    resp = requests.post(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        json={
            "model": "local",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        },
        timeout=180,
    )
    elapsed = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, elapsed, usage


def _generate_direct(prompt: str, max_tokens: int = 512) -> tuple[str, float, dict]:
    """In-process generation via llama_cpp (ZENAI_LLM_ENGINE=llamacpp_direct)."""
    t0 = time.time()
    resp = _direct_llm.create_chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    elapsed = time.time() - t0
    content = resp["choices"][0]["message"]["content"]
    usage = resp.get("usage", {})
    return content, elapsed, usage


def build_prompt(tc: dict) -> str:
    """Build the LLM prompt from a test case."""
    return (
        f"Fix this Rust compilation error. Return ONLY the corrected lines, "
        f"no explanations, no markdown fences.\n\n"
        f"Error: {tc['error_code']} -> {tc['error_message']}\n"
        f"File: {tc['file']}, line {tc['line']}\n\n"
        f"Code context:\n{tc['context']}\n\n"
        f"The line marked with >>> has the error. "
        f"Return ONLY the fixed version of the code (corrected lines):"
    )


# ── Scoring ──────────────────────────────────────────────────────────────

def score_response(response: str, tc: dict) -> dict:
    """Score a response for accuracy and quality.

    Returns:
        dict with keys: accurate, has_anti_pattern, code_only, concise,
                        response_length, line_count, score (0-100)
    """
    resp_lower = response.lower()

    # Accuracy: does it contain ANY expected pattern?
    accurate = any(pat.lower() in resp_lower for pat in tc.get("expected_patterns", []))

    # Anti-patterns: things that indicate a wrong fix
    has_anti = any(pat.lower() in resp_lower for pat in tc.get("anti_patterns", []))
    if has_anti:
        accurate = False  # Anti-pattern overrides

    # Code quality
    has_explanation = any(
        w in resp_lower
        for w in ["the error", "the issue", "the problem", "here's", "note:", "explanation"]
    )
    has_markdown = "```" in response
    is_code_only = not has_explanation and not has_markdown
    line_count = len(response.strip().splitlines())
    is_concise = line_count <= 15

    # Composite score
    difficulty = tc.get("difficulty", "medium")
    weight = DIFFICULTY_WEIGHT.get(difficulty, 1.0)

    score = 0.0
    if accurate:
        score += 60 * weight  # Correctness is king
    if is_code_only:
        score += 20 * weight  # Following instructions
    if is_concise:
        score += 10 * weight  # Not verbose
    if not has_anti:
        score += 10 * weight  # No wrong patterns

    return {
        "accurate": accurate,
        "has_anti_pattern": has_anti,
        "code_only": is_code_only,
        "concise": is_concise,
        "response_length": len(response),
        "line_count": line_count,
        "score": score,
    }


# ── Main ─────────────────────────────────────────────────────────────────

def load_test_cases(path: Path) -> list[dict]:
    """Load test cases from JSON file."""
    with open(path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    cases = data.get("cases", [])
    print(f"Loaded {len(cases)} test cases from {path.name}")
    return cases


def validate_test_cases(cases: list[dict]) -> bool:
    """Validate test case format."""
    required = {"id", "name", "error_code", "error_message", "file", "line", "context", "expected_patterns"}
    ok = True
    for i, tc in enumerate(cases):
        missing = required - set(tc.keys())
        if missing:
            print(f"  Case {i} ({tc.get('id', '?')}): missing fields: {missing}")
            ok = False
        if not tc.get("expected_patterns"):
            print(f"  Case {i} ({tc.get('id', '?')}): expected_patterns is empty")
            ok = False
    if ok:
        print("  All test cases valid!")
    return ok


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark GGUF models on Rust compile error fixing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--models", type=str, default="",
                        help="Comma-separated model names to test (default: all available)")
    parser.add_argument("--models-dir", type=str, default=DEFAULT_MODELS_DIR,
                        help=f"Directory containing .gguf model files (env: SWARM_MODELS_DIR, default: {DEFAULT_MODELS_DIR})")
    parser.add_argument("--test-cases", type=str, default="",
                        help="Path to test cases JSON (default: benchmarks/test_cases.json)")
    parser.add_argument("--port", type=int, default=8095,
                        help="Port for llama-server (default: 8095)")
    parser.add_argument("--ctx-size", type=int, default=4096,
                        help="Context size (default: 4096)")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Server startup timeout in seconds (default: 180)")
    parser.add_argument("--warmup", action="store_true",
                        help="Send warmup prompt before benchmarking each model")
    parser.add_argument("--validate", action="store_true",
                        help="Validate test cases format only, don't run benchmark")
    parser.add_argument("--output", type=str, default="",
                        help="Output JSON path (default: auto-generated in benchmarks/results/)")
    parser.add_argument("--backend", type=str, default="auto",
                        choices=["auto", "cpu", "vulkan"],
                        help="Compute backend: auto (GPU offload), cpu (CPU only), vulkan (AMD/NVIDIA GPU)")
    parser.add_argument("--engine", type=str,
                        default=os.environ.get("ZENAI_LLM_ENGINE", "llamacpp_direct"),
                        choices=["llamacpp_direct", "server"],
                        help="LLM engine: llamacpp_direct (in-process, fastest) or server (HTTP llama-server)")
    args = parser.parse_args()

    model_dir = Path(args.models_dir)
    bench_dir = Path(__file__).parent

    # Detect and display hardware
    print("Detecting hardware...")
    hw_info = detect_hardware()
    print(f"  CPU: {hw_info.get('cpu', 'unknown')}")
    if hw_info.get("cpu_cores"):
        print(f"       {hw_info['cpu_cores']} cores / {hw_info.get('cpu_threads', '?')} threads")
    if hw_info.get("cpu_features"):
        print(f"       Features: {', '.join(hw_info['cpu_features'])}")
    print(f"  GPU: {hw_info.get('gpu', 'unknown')}")
    print(f"  NPU: {hw_info.get('npu', 'unknown')}")
    print(f"  Backend: {args.backend}")
    print(f"  Engine: {args.engine}")
    if args.engine != "llamacpp_direct":
        print(f"  Server: {find_llama_server()}")
    print(f"  Models: {model_dir}")
    print()

    # Load test cases
    tc_path = Path(args.test_cases) if args.test_cases else bench_dir / "test_cases.json"
    cases = load_test_cases(tc_path)

    if args.validate:
        validate_test_cases(cases)
        return

    # Determine which models to test
    if args.models:
        selected = [m.strip() for m in args.models.split(",")]
        model_list = {k: v for k, v in MODELS.items() if k in selected}
    else:
        model_list = MODELS

    # Filter to available models
    print(f"\nScanning {model_dir} for models...")
    available: list[tuple[str, str, float]] = []
    for name, filename in model_list.items():
        path = model_dir / filename
        if path.exists():
            size_gb = path.stat().st_size / (1024**3)
            available.append((name, str(path), size_gb))
            print(f"  [OK] {name} ({size_gb:.1f} GB)")
        else:
            print(f"  [--] {name} (not found: {filename})")

    if not available:
        print("\nNo models found! Check --models-dir path.")
        return

    print(f"\nBenchmarking {len(available)} models x {len(cases)} test cases")
    print(f"Port: {args.port}, Context: {args.ctx_size}, Timeout: {args.timeout}s")
    print()

    # ── Run benchmark ──
    all_results: dict[str, dict] = {}
    total_start = time.time()

    for model_name, model_path, size_gb in available:
        print(f"\n{'='*70}")
        print(f"TESTING: {model_name} ({size_gb:.1f} GB)")
        print(f"{'='*70}")

        try:
            if args.engine == "llamacpp_direct":
                print(f"  Loading model in-process (llamacpp_direct)...")
                from llama_cpp import Llama
                t0 = time.time()
                global _direct_llm
                ngl = int(os.environ.get("ZENAI_GPU_LAYERS", "-1"))
                _direct_llm = Llama(
                    model_path=model_path,
                    verbose=False,
                    n_gpu_layers=ngl,
                    n_ctx=args.ctx_size,
                    flash_attn=True,
                )
                load_time = time.time() - t0
                print(f"  Ready in {load_time:.1f}s (n_gpu_layers={ngl})")
                if args.warmup:
                    print("  Warming up...")
                    _generate_direct("Fix: let x: String = 42;", max_tokens=10)
            else:
                print(f"  Loading model ({args.backend} backend)...")
                load_time = start_server(model_path, args.port, args.ctx_size, args.timeout, args.backend)
                print(f"  Ready in {load_time:.1f}s")
                if args.warmup:
                    print("  Warming up...")
                    warmup_server(args.port)

        except (RuntimeError, TimeoutError, FileNotFoundError, ImportError) as exc:
            print(f"  FAILED: {exc}")
            all_results[model_name] = {
                "status": "FAILED_TO_START",
                "error": str(exc),
                "size_gb": size_gb,
            }
            if args.engine != "llamacpp_direct":
                stop_server()
            time.sleep(2)
            continue

        model_results = {
            "status": "ok",
            "load_time": load_time,
            "size_gb": size_gb,
            "model_path": model_path,
            "tests": [],
        }

        total_time = 0.0
        total_score = 0.0
        correct = 0
        max_possible_score = 0.0

        for tc in cases:
            prompt = build_prompt(tc)
            difficulty = tc.get("difficulty", "medium")
            weight = DIFFICULTY_WEIGHT.get(difficulty, 1.0)
            max_possible_score += 100 * weight

            try:
                response, elapsed, usage = generate(args.port, prompt)
                scores = score_response(response, tc)
                total_time += elapsed
                total_score += scores["score"]

                if scores["accurate"]:
                    correct += 1

                status = "PASS" if scores["accurate"] else "FAIL"
                print(f"  [{status}] {tc['name']}: {elapsed:.1f}s, "
                      f"score={scores['score']:.0f}, {scores['line_count']} lines")
                if not scores["accurate"]:
                    preview = response.strip().splitlines()[0][:100] if response.strip() else "(empty)"
                    print(f"        -> {preview}")

                model_results["tests"].append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "difficulty": difficulty,
                    "accurate": scores["accurate"],
                    "has_anti_pattern": scores["has_anti_pattern"],
                    "code_only": scores["code_only"],
                    "concise": scores["concise"],
                    "elapsed": round(elapsed, 2),
                    "score": round(scores["score"], 1),
                    "response_length": scores["response_length"],
                    "line_count": scores["line_count"],
                    "tokens": usage,
                    "response_preview": response.strip()[:200],
                })

            except Exception as exc:
                print(f"  [ERR] {tc['name']}: {exc}")
                model_results["tests"].append({
                    "id": tc["id"],
                    "name": tc["name"],
                    "accurate": False,
                    "error": str(exc),
                    "elapsed": 0,
                    "score": 0,
                })

        # Aggregate
        n = len(cases)
        model_results["total_time"] = round(total_time, 1)
        model_results["avg_time"] = round(total_time / n, 1) if n else 0
        model_results["accuracy_pct"] = round(correct / n * 100, 1) if n else 0
        model_results["correct"] = correct
        model_results["total_score"] = round(total_score, 1)
        model_results["max_score"] = round(max_possible_score, 1)
        model_results["normalized_score"] = round(total_score / max_possible_score * 100, 1) if max_possible_score else 0

        # Speed score: faster is better (0-100, 5s=100, 60s=0)
        speed_score = max(0, min(100, (60 - model_results["avg_time"]) / 55 * 100))
        model_results["speed_score"] = round(speed_score, 1)

        # Combined score: 60% accuracy + 25% speed + 15% quality
        combined = (
            model_results["normalized_score"] * 0.60 +
            speed_score * 0.25 +
            (sum(1 for t in model_results["tests"] if t.get("code_only")) / n * 100 if n else 0) * 0.15
        )
        model_results["combined_score"] = round(combined, 1)

        print(f"\n  SUMMARY: {correct}/{n} correct ({model_results['accuracy_pct']}%), "
              f"avg {model_results['avg_time']}s, combined={model_results['combined_score']:.0f}/100")

        all_results[model_name] = model_results
        if args.engine == "llamacpp_direct":
            _direct_llm = None  # Unload model
        else:
            stop_server()
        time.sleep(3)  # Cool down

    total_elapsed = time.time() - total_start

    # ── Final comparison table ──
    print(f"\n\n{'='*80}")
    print(f"FINAL COMPARISON  ({len(available)} models, {len(cases)} tests, {total_elapsed:.0f}s total)")
    print(f"{'='*80}\n")

    header = f"{'#':<3} {'Model':<24} {'Size':>5} {'Accuracy':>9} {'Avg(s)':>7} {'Score':>7} {'Speed':>6} {'Combined':>9}"
    print(header)
    print("-" * len(header))

    ranked = sorted(
        [(name, r) for name, r in all_results.items() if r.get("status") == "ok"],
        key=lambda x: -x[1]["combined_score"],
    )

    for i, (name, r) in enumerate(ranked, 1):
        marker = " *" if i == 1 else "  "
        print(f"{i:<3}{name:<24} {r['size_gb']:>4.1f}G "
              f"{r['accuracy_pct']:>8.0f}% {r['avg_time']:>6.1f}s "
              f"{r['normalized_score']:>6.1f} {r['speed_score']:>5.1f} "
              f"{r['combined_score']:>8.1f}{marker}")

    # Failed
    failed = [(name, r) for name, r in all_results.items() if r.get("status") != "ok"]
    for name, r in failed:
        print(f"    {name:<24} {'FAILED':<5} {r.get('error', '')[:40]}")

    if ranked:
        w = ranked[0]
        print(f"\nWINNER: {w[0]} (combined score {w[1]['combined_score']:.0f}/100, "
              f"{w[1]['accuracy_pct']:.0f}% accuracy, {w[1]['avg_time']:.1f}s avg)")

    # ── Save results ──
    if args.output:
        out_path = Path(args.output)
    else:
        results_dir = bench_dir / "results"
        results_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = results_dir / f"{ts}_results.json"

    output = {
        "benchmark_version": "1.1",
        "timestamp": datetime.now().isoformat(),
        "total_elapsed_s": round(total_elapsed, 1),
        "hardware": hw_info,
        "settings": {
            "port": args.port,
            "ctx_size": args.ctx_size,
            "timeout": args.timeout,
            "warmup": args.warmup,
            "engine": args.engine,
            "backend": args.backend,
            "llama_server": find_llama_server() if args.engine != "llamacpp_direct" else "N/A (in-process)",
            "test_cases_file": str(tc_path),
            "models_dir": str(model_dir),
        },
        "test_case_count": len(cases),
        "model_count": len(available),
        "ranking": [name for name, _ in ranked],
        "results": all_results,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
