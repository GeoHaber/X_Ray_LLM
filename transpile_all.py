#!/usr/bin/env python3
"""Transpile all GeorgeHaber Python repos to Rust with LLM-assisted error fixing.

Usage:
    python transpile_all.py                    # all repos, smallest first
    python transpile_all.py --repo Video_Transcode  # single repo
    python transpile_all.py --fix-only         # skip transpile, just fix existing rust_output
    python transpile_all.py --model gemma4     # choose model (gemma4|qwen-coder|deepseek)
"""
import argparse
import functools
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
print = functools.partial(print, flush=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("transpile_all")

# ── Config ───────────────────────────────────────────────────────────────

REPOS_ROOT = Path(r"C:\Users\dvdze\Documents\GitHub\GeorgeHaber")
LLAMA_BIN = Path(os.environ.get("ZENAI_LLAMA_SERVER", r"C:\AI\_bin\llama-server.exe"))
MODELS_DIR = Path(os.environ.get("SWARM_MODELS_DIR", r"C:\AI\Models"))
PORT = 8090

MODELS = {
    "gemma4":       str(MODELS_DIR / "gemma-4-E4B-it-Q4_K_M.gguf"),
    "qwen-coder":   str(MODELS_DIR / "Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"),
    "deepseek":     str(MODELS_DIR / "deepseek-coder-6.7b-instruct.Q4_K_M.gguf"),
    "qwen-coder-7": str(MODELS_DIR / "qwen2.5-coder-7b-instruct-q4_k_m.gguf"),
    "devstral":     str(MODELS_DIR / "Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf"),
}
DEFAULT_MODEL = "gemma4"

# Repos to transpile, ordered by size (smallest first for fast wins)
REPOS = [
    "Reference_Chek",
    "Keep_1080p_or_BEST",
    "Multy_Video_Player",
    "Scan_and_Play",
    "Video_Transcode",
    "ETC",
    "SmartCalendar",
    "LLM_TEST_BED",
    "chat-widget-server",
    "MARKET_AI",
    "Add_Language",
    "AionUi",
    "X_Ray_LLM",
    "zen_core_libs",
    "ZenAIos-Dashboard",
    "ZEN_AI_RAG",
    "main-app",
]

# Skip patterns — files/dirs that shouldn't be transpiled
SKIP_PATTERNS = [
    "__pycache__", "node_modules", "venv", ".venv", ".git",
    "rust_output", "__N_tmp", "migrations", ".tox", "dist", "build",
    "egg-info", "site-packages", ".eggs",
]

MAX_FIX_ROUNDS = 5
MAX_LLM_CALLS_PER_REPO = 200
FIXES_PER_ROUND = 30


# ── LLM Engines ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = "Fix Rust errors. Return ONLY the corrected code line(s). No explanation."
STOP_SEQUENCES = ["\n", "```", "### ", "Explanation:", "Note:", "The error is"]


class DirectLLM:
    """In-process llama-cpp-python engine (ZENAI_LLM_ENGINE=llamacpp_direct).

    No HTTP server overhead — fastest path. Uses Vulkan/CPU automatically.
    """

    def __init__(self, model_path: str):
        from llama_cpp import Llama
        self.model_path = model_path
        log.info("Loading model in-process: %s", Path(model_path).name)
        t0 = time.time()
        ngl = int(os.environ.get("ZENAI_GPU_LAYERS", "-1"))
        self._llm = Llama(
            model_path=model_path,
            verbose=False,
            n_gpu_layers=ngl,
            n_ctx=2048,
            flash_attn=True,
        )
        log.info("Model loaded in %.1fs (n_gpu_layers=%d)", time.time() - t0, ngl)

    def start(self, timeout: int = 0):
        """No-op — model already loaded in __init__."""
        # Warmup: one call to compile any Vulkan shaders
        log.info("Warming up...")
        self.generate("Fix: let x: String = 42;", max_tokens=10)
        log.info("LLM ready (in-process)")

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        resp = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
            stop=STOP_SEQUENCES,
        )
        return resp["choices"][0]["message"]["content"]

    def stop(self):
        del self._llm
        self._llm = None
        log.info("LLM unloaded")


class LLMServer:
    """Manages llama-server lifecycle (HTTP-based)."""

    def __init__(self, model_path: str, port: int = PORT):
        self.model_path = model_path
        self.port = port
        self._proc = None

    def start(self, timeout: int = 180):
        log.info("Starting LLM server: %s", Path(self.model_path).name)
        self._proc = subprocess.Popen(
            [str(LLAMA_BIN), "--model", self.model_path,
             "--port", str(self.port), "-ngl", "-1", "-c", "2048",
             "-np", "1", "--flash-attn", "on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import requests
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"llama-server exited rc={self._proc.returncode}")
            try:
                r = requests.get(f"http://127.0.0.1:{self.port}/health", timeout=2)
                if r.status_code == 200 and r.json().get("status") == "ok":
                    log.info("LLM healthy on port %d, warming up...", self.port)
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise TimeoutError(f"LLM did not start within {timeout}s")
        # Warmup: 2 requests to compile Vulkan shaders (outside timeout loop)
        for i in range(2):
            try:
                requests.post(
                    f"http://127.0.0.1:{self.port}/v1/chat/completions",
                    json={"model": "local",
                          "messages": [{"role": "user", "content": "Fix Rust: let x: String = 42;"}],
                          "max_tokens": 10},
                    timeout=300,
                )
            except Exception as e:
                log.warning("Warmup %d failed: %s", i, e)
        log.info("LLM ready (server mode)")

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        import requests
        resp = requests.post(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            json={
                "model": "local",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
                "stop": STOP_SEQUENCES,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
            self._proc = None
            log.info("LLM server stopped")


# ── Transpile ────────────────────────────────────────────────────────────

def count_py_files(repo_dir: Path) -> int:
    count = 0
    for f in repo_dir.rglob("*.py"):
        if not any(skip in str(f) for skip in SKIP_PATTERNS):
            count += 1
    return count


def transpile_repo(repo_dir: Path, output_dir: Path) -> dict:
    """Run the X-Ray transpiler on a repo. Returns result dict."""
    sys.path.insert(0, str(Path(__file__).parent))
    from xray.transpiler import TranspileConfig, Transpiler

    config = TranspileConfig(
        output_dir=str(output_dir),
        crate_name=repo_dir.name.lower().replace("-", "_").replace(" ", "_"),
        use_llm=False,  # We do LLM fixes separately
        generate_tests=True,
        generate_cargo_toml=True,
        preserve_comments=True,
        type_inference=True,
        error_strategy="anyhow",
        async_runtime="tokio",
    )

    t0 = time.time()
    transpiler = Transpiler(config)
    result = transpiler.transpile_directory(str(repo_dir))
    elapsed = time.time() - t0

    return {
        "modules": result.modules_transpiled,
        "files": len(result.files_written),
        "compile_success": result.compile_success,
        "compile_errors": len(result.compile_errors),
        "elapsed": elapsed,
        "error_lines": result.compile_errors,
    }


# ── Compile + Fix Loop ──────────────────────────────────────────────────

def try_compile(rust_dir: Path) -> tuple[bool, list[str]]:
    if not (rust_dir / "Cargo.toml").exists():
        return False, ["Cargo.toml not found"]
    proc = subprocess.run(
        ["cargo", "check"], cwd=str(rust_dir),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    if proc.returncode == 0:
        return True, []
    return False, (proc.stderr or "").splitlines()


def parse_errors(error_lines: list[str]) -> list[dict]:
    entries = []
    i = 0
    while i < len(error_lines):
        line = error_lines[i].strip()
        code_match = re.match(r"error\[(E\d+)\]:\s*(.+)", line)
        parse_match = re.match(r"error:\s*(.+)", line) if not code_match else None
        if code_match or parse_match:
            code = code_match.group(1) if code_match else "parse"
            message = (code_match or parse_match).group(2 if code_match else 1)
            loc_match = None
            for j in range(i + 1, min(i + 5, len(error_lines))):
                loc_match = re.search(r"-->\s*src[/\\](\S+\.rs):(\d+)", error_lines[j])
                if loc_match:
                    break
            if loc_match:
                entries.append({
                    "code": code, "message": message,
                    "file": loc_match.group(1), "line": int(loc_match.group(2)),
                })
        i += 1
    return entries


def extract_code_block(text: str) -> str:
    m = re.search(r"```(?:rust)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def fix_loop(rust_dir: Path, llm: LLMServer) -> dict:
    """Run iterative LLM fix loop on compiled Rust output."""
    success, errors = try_compile(rust_dir)
    initial_errors = parse_errors(errors)

    if success:
        return {"initial": 0, "final": 0, "rounds": 0, "llm_calls": 0, "success": True}

    log.info("  Fix loop: %d initial errors", len(initial_errors))
    llm_calls = 0

    for round_num in range(1, MAX_FIX_ROUNDS + 1):
        if llm_calls >= MAX_LLM_CALLS_PER_REPO:
            break

        error_entries = parse_errors(errors)
        if not error_entries:
            break

        # Group by file
        by_file: dict[str, list[dict]] = {}
        for e in error_entries:
            by_file.setdefault(e["file"], []).append(e)

        files_modified = set()
        round_fixes = 0

        for src_file, file_errors in by_file.items():
            if llm_calls >= MAX_LLM_CALLS_PER_REPO or round_fixes >= FIXES_PER_ROUND:
                break

            src_path = rust_dir / "src" / src_file
            if not src_path.exists():
                continue

            source = src_path.read_text(encoding="utf-8", errors="replace")
            lines = source.splitlines()
            file_errors.sort(key=lambda e: e["line"], reverse=True)

            for entry in file_errors[:10]:
                if llm_calls >= MAX_LLM_CALLS_PER_REPO or round_fixes >= FIXES_PER_ROUND:
                    break

                err_line = entry["line"] - 1
                if err_line >= len(lines):
                    continue

                # Show ±3 lines of context but only ask for the single error line fix
                ctx_start = max(0, err_line - 3)
                ctx_end = min(len(lines), err_line + 4)
                context_numbered = "\n".join(
                    f"{'>>>' if i + ctx_start == err_line else '   '} {i + ctx_start + 1:4d} | {l}"
                    for i, l in enumerate(lines[ctx_start:ctx_end])
                )

                prompt = (
                    f"Fix Rust error {entry['code']}: {entry['message']}\n"
                    f"{entry['file']}:{entry['line']}\n\n"
                    f"{context_numbered}\n\n"
                    f"Return ONLY the fixed line {entry['line']}. One line, no explanation:"
                )

                try:
                    t_call = time.time()
                    raw = llm.generate(prompt, max_tokens=50)
                    call_time = time.time() - t_call
                    llm_calls += 1
                    log.info("    LLM call %d: %.1fs (%s:%d %s)",
                             llm_calls, call_time, entry["file"], entry["line"], entry["code"])
                    fix_text = extract_code_block(raw) or raw.strip()
                    # Strip markdown artifacts and line number prefixes
                    fix_text = re.sub(r"^```(?:rust)?\s*", "", fix_text).strip()
                    # Take only first non-empty line
                    fix_line = ""
                    for fl in fix_text.splitlines():
                        stripped = re.sub(r"^(?:>>>|   )\s*\d+\s*\|\s?", "", fl).strip()
                        if stripped and not stripped.startswith("```"):
                            fix_line = stripped
                            break

                    if fix_line and fix_line != lines[err_line].strip():
                        # Preserve original indentation
                        indent = len(lines[err_line]) - len(lines[err_line].lstrip())
                        lines[err_line] = " " * indent + fix_line
                        files_modified.add(src_file)
                        round_fixes += 1
                except Exception as exc:
                    log.debug("Fix failed: %s:%d -> %s", entry["file"], entry["line"], exc)

            if src_file in files_modified:
                src_path.write_text("\n".join(lines), encoding="utf-8")

        log.info("  Round %d: applied %d fixes to %d files", round_num, round_fixes, len(files_modified))

        if files_modified:
            success, errors = try_compile(rust_dir)
            final_errors = parse_errors(errors)
            log.info("  After round %d: %d errors (%d LLM calls)",
                     round_num, len(final_errors), llm_calls)
            if success:
                log.info("  COMPILE SUCCESS on round %d!", round_num)
                break
        else:
            break

    final_count = len(parse_errors(errors)) if not success else 0
    return {
        "initial": len(initial_errors),
        "final": final_count,
        "rounds": round_num,
        "llm_calls": llm_calls,
        "success": success,
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Transpile all repos to Rust")
    parser.add_argument("--repo", type=str, default="", help="Single repo name to transpile")
    parser.add_argument("--fix-only", action="store_true", help="Skip transpile, just run fix loop")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        choices=list(MODELS.keys()), help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--no-fix", action="store_true", help="Transpile only, skip fix loop")
    parser.add_argument("--engine", type=str,
                        default=os.environ.get("ZENAI_LLM_ENGINE", "llamacpp_direct"),
                        choices=["llamacpp_direct", "server"],
                        help="LLM engine: llamacpp_direct (in-process, fastest) or server (HTTP)")
    args = parser.parse_args()

    model_path = MODELS[args.model]
    if not Path(model_path).exists():
        print(f"Model not found: {model_path}")
        return

    # Determine repos to process
    if args.repo:
        repos = [args.repo]
    else:
        repos = [r for r in REPOS if (REPOS_ROOT / r).is_dir()]

    print(f"Model:  {args.model} ({Path(model_path).name})")
    print(f"Engine: {args.engine}")
    print(f"Repos:  {len(repos)}")
    print()

    # Start LLM (shared across all repos)
    if args.engine == "llamacpp_direct":
        llm = DirectLLM(model_path)
    else:
        llm = LLMServer(model_path)
    if not args.no_fix:
        llm.start()

    all_results = {}
    total_start = time.time()

    try:
        for repo_name in repos:
            repo_dir = REPOS_ROOT / repo_name
            if not repo_dir.is_dir():
                continue

            py_count = count_py_files(repo_dir)
            if py_count == 0:
                continue

            output_dir = repo_dir / "rust_output"
            print(f"\n{'='*60}")
            print(f"REPO: {repo_name} ({py_count} Python files)")
            print(f"{'='*60}")

            result = {"repo": repo_name, "py_files": py_count}

            # Step 1: Transpile
            if not args.fix_only:
                try:
                    log.info("Transpiling...")
                    tr = transpile_repo(repo_dir, output_dir)
                    result.update({
                        "modules": tr["modules"],
                        "rust_files": tr["files"],
                        "transpile_time": tr["elapsed"],
                        "initial_compile": tr["compile_success"],
                        "initial_errors": tr["compile_errors"],
                    })
                    log.info("  Transpiled %d modules -> %d Rust files in %.1fs",
                             tr["modules"], tr["files"], tr["elapsed"])
                    if tr["compile_success"]:
                        log.info("  Compiles clean!")
                        result["fix_result"] = {"initial": 0, "final": 0, "success": True}
                except Exception as exc:
                    log.error("  Transpile failed: %s", exc)
                    result["error"] = str(exc)
                    all_results[repo_name] = result
                    continue

            # Step 2: Fix loop
            if not args.no_fix and not result.get("fix_result", {}).get("success"):
                if (output_dir / "Cargo.toml").exists():
                    try:
                        fix = fix_loop(output_dir, llm)
                        result["fix_result"] = fix
                        pct = (1 - fix["final"] / max(fix["initial"], 1)) * 100
                        log.info("  Fix result: %d -> %d errors (%.1f%% reduction, %d LLM calls)",
                                 fix["initial"], fix["final"], pct, fix["llm_calls"])
                    except Exception as exc:
                        log.error("  Fix loop failed: %s", exc)
                        result["fix_error"] = str(exc)

            all_results[repo_name] = result

    finally:
        if not args.no_fix:
            llm.stop()

    total_elapsed = time.time() - total_start

    # ── Summary ──
    print(f"\n\n{'='*70}")
    print(f"TRANSPILATION SUMMARY ({total_elapsed:.0f}s total)")
    print(f"{'='*70}\n")

    print(f"{'Repo':<24} {'Py':>4} {'Rust':>5} {'Initial':>8} {'Final':>6} {'Fix%':>6} {'LLM':>5} {'Status':>8}")
    print("-" * 75)

    total_initial = 0
    total_final = 0
    clean_count = 0

    for repo_name, r in all_results.items():
        fix = r.get("fix_result", {})
        ini = fix.get("initial", r.get("initial_errors", "?"))
        fin = fix.get("final", "?")
        llm_c = fix.get("llm_calls", 0)
        success = fix.get("success", False)

        if isinstance(ini, int) and isinstance(fin, int):
            pct = f"{(1 - fin / max(ini, 1)) * 100:.0f}%" if ini > 0 else "100%"
            total_initial += ini
            total_final += fin
        else:
            pct = "--"

        if success:
            status = "CLEAN"
            clean_count += 1
        elif "error" in r:
            status = "ERROR"
        else:
            status = f"{fin} err"

        print(f"{repo_name:<24} {r.get('py_files', '?'):>4} {r.get('rust_files', '?'):>5} "
              f"{ini:>8} {fin:>6} {pct:>6} {llm_c:>5} {status:>8}")

    print("-" * 75)
    pct_total = f"{(1 - total_final / max(total_initial, 1)) * 100:.1f}%" if total_initial else "--"
    print(f"{'TOTAL':<24} {'':>4} {'':>5} {total_initial:>8} {total_final:>6} {pct_total:>6}")
    print(f"\nClean compiles: {clean_count}/{len(all_results)}")
    print(f"Total time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")

    # Save results
    results_path = Path(__file__).parent / "transpile_results.json"
    with open(results_path, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": args.model,
            "total_elapsed": total_elapsed,
            "results": all_results,
        }, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")


if __name__ == "__main__":
    main()
