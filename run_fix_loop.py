#!/usr/bin/env python3
"""Run aggressive LLM compile-fix loop on existing Rust output."""
import logging
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    stream=sys.stdout,
)

log = logging.getLogger("fix_loop")

MODEL_PATH = r"C:\AI\Models\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf"
RUST_DIR = Path(r"C:\Users\dvdze\Documents\GitHub\GeorgeHaber\Video_Transcode\rust_output")
MAX_ROUNDS = 5
MAX_LLM_CALLS = 200
FIXES_PER_ROUND = 30  # More errors per round


def try_compile() -> tuple[bool, list[str]]:
    import subprocess
    proc = subprocess.run(
        ["cargo", "check"],
        cwd=str(RUST_DIR),
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=180,
    )
    if proc.returncode == 0:
        return True, []
    return False, (proc.stderr or "").splitlines()


def parse_errors(error_lines: list[str]) -> list[dict]:
    entries = []
    i = 0
    while i < len(error_lines):
        line = error_lines[i].strip()
        # Match: error[E0425]: message  OR  error: message
        code_match = re.match(r'error\[(E\d+)\]:\s*(.+)', line)
        parse_match = re.match(r'error:\s*(.+)', line) if not code_match else None

        if code_match or parse_match:
            if code_match:
                code = code_match.group(1)
                message = code_match.group(2)
            else:
                code = "parse"
                message = parse_match.group(1)

            # Scan next lines for location
            loc_match = None
            for j in range(i + 1, min(i + 5, len(error_lines))):
                loc_match = re.search(r'-->\s*src[/\\](\S+\.rs):(\d+)', error_lines[j])
                if loc_match:
                    break
            if loc_match:
                entries.append({
                    "code": code,
                    "message": message,
                    "file": loc_match.group(1),
                    "line": int(loc_match.group(2)),
                })
        i += 1
    return entries


class DirectLLMClient:
    """Direct OpenAI-compatible client for llama-server."""
    def __init__(self, base_url: str = "http://127.0.0.1:8090"):
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        import requests
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": "local",
                "messages": [
                    {"role": "system", "content": "You are a Rust compiler error fixer. Return ONLY corrected code, no explanations."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def create_llm():
    """Create LLM backend using zen_core_libs."""
    from zen_core_libs.llm import LlamaServerManager
    mgr = LlamaServerManager()
    mgr.start(MODEL_PATH, port=8090, gpu_layers=-1, timeout=120, ctx_size=4096)
    adapter = DirectLLMClient(base_url="http://127.0.0.1:8090")
    return mgr, adapter


def extract_code_block(text: str) -> str:
    """Extract code from markdown fences if present."""
    m = re.search(r'```(?:rust)?\s*\n(.*?)```', text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


def main():
    t0 = time.time()

    print(f"Rust output: {RUST_DIR}")
    print(f"Model: {MODEL_PATH}")
    print(f"Max rounds: {MAX_ROUNDS}, Max LLM calls: {MAX_LLM_CALLS}")
    print()

    # Initial compile
    success, errors = try_compile()
    initial_errors = parse_errors(errors)
    print(f"Initial: {len(initial_errors)} unique errors")
    if success:
        print("Already compiles clean!")
        return

    # Start LLM
    print("Starting LLM server...")
    mgr, adapter = create_llm()
    print("LLM ready")

    llm_calls = 0
    try:
        for round_num in range(1, MAX_ROUNDS + 1):
            if llm_calls >= MAX_LLM_CALLS:
                print(f"LLM call budget exhausted ({llm_calls}/{MAX_LLM_CALLS})")
                break

            error_entries = parse_errors(errors)
            if not error_entries:
                break

            print(f"\nRound {round_num}/{MAX_ROUNDS}: {len(error_entries)} errors, {llm_calls} LLM calls so far")

            # Group errors by file for efficiency
            by_file: dict[str, list[dict]] = {}
            for e in error_entries:
                by_file.setdefault(e["file"], []).append(e)

            files_modified = set()
            round_fixes = 0

            for src_file, file_errors in by_file.items():
                if llm_calls >= MAX_LLM_CALLS:
                    break
                if round_fixes >= FIXES_PER_ROUND:
                    break

                src_path = RUST_DIR / "src" / src_file
                if not src_path.exists():
                    continue

                source = src_path.read_text(encoding="utf-8", errors="replace")
                lines = source.splitlines()

                # Sort errors by line number (descending) to avoid offset issues
                file_errors.sort(key=lambda e: e["line"], reverse=True)

                for entry in file_errors[:10]:  # Max 10 per file per round
                    if llm_calls >= MAX_LLM_CALLS or round_fixes >= FIXES_PER_ROUND:
                        break

                    err_line = entry["line"] - 1
                    start = max(0, err_line - 10)
                    end = min(len(lines), err_line + 11)
                    context_lines = lines[start:end]
                    context_with_numbers = "\n".join(
                        f"{'>>>' if i + start == err_line else '   '} {i + start + 1:4d} | {l}"
                        for i, l in enumerate(context_lines)
                    )

                    prompt = (
                        "Fix this Rust compilation error. Return ONLY the corrected line(s), "
                        "no explanations, no markdown fences.\n\n"
                        f"Error: {entry['code']} -> {entry['message']}\n"
                        f"File: {entry['file']}, line {entry['line']}\n\n"
                        f"Code context:\n{context_with_numbers}\n\n"
                        f"The line marked with >>> has the error. "
                        f"Return ONLY the fixed version of lines {start + 1}-{end} "
                        f"(the same {end - start} lines, corrected):"
                    )

                    try:
                        raw = adapter.generate(prompt, max_tokens=512)
                        llm_calls += 1
                        fix_text = extract_code_block(raw) or raw.strip()
                        fix_lines = fix_text.splitlines()

                        if fix_lines and len(fix_lines) >= 1:
                            cleaned = []
                            for fl in fix_lines:
                                stripped = re.sub(r'^(?:>>>|   )\s*\d+\s*\|\s?', '', fl)
                                cleaned.append(stripped)
                            lines[start:end] = cleaned
                            files_modified.add(src_file)
                            round_fixes += 1
                    except Exception as exc:
                        log.debug("Fix failed: %s:%d -> %s", entry["file"], entry["line"], exc)

                # Write modified file
                if src_file in files_modified:
                    src_path.write_text("\n".join(lines), encoding="utf-8")

            print(f"  Applied {round_fixes} fixes to {len(files_modified)} files")

            # Recompile
            success, errors = try_compile()
            new_errors = parse_errors(errors)
            print(f"  After round {round_num}: {len(new_errors)} errors")

            if success:
                print(f"\nCOMPILE SUCCESS on round {round_num}!")
                break

    finally:
        mgr.stop()

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"FIX LOOP COMPLETE in {elapsed:.1f}s")
    print(f"  Rounds: {round_num}")
    print(f"  LLM calls: {llm_calls}")
    print(f"  Initial errors: {len(initial_errors)}")
    final_errors = parse_errors(errors) if not success else []
    print(f"  Final errors: {len(final_errors)}")
    pct = (1 - len(final_errors) / max(len(initial_errors), 1)) * 100
    print(f"  Reduction: {pct:.1f}%")
    print(f"  Compile success: {success}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
