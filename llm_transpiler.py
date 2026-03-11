#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM-powered Python to Rust transpiler using llama-server.exe (llama.cpp).
Transcodes Python to production-ready Rust via local CPU inference.

Usage:
    python llm_transpiler.py                           # auto-spawn llama-server
    python llm_transpiler.py --already-running         # connect to existing server
    python llm_transpiler.py --model "Qwen3.5-32B"    # specific model
"""

import asyncio
import json
import logging
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# ── Encoding fix for Windows ───────────────────────────────────────────────

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("transpiler")

# ── Configuration ──────────────────────────────────────────────────────────

LLAMA_PORT = 8888
MODELS_DIR = Path("C:/AI/Models")
SERVER_BIN = Path(__file__).parent.parent / "LLM_TEST_BED" / "bin" / "llama-server.exe"
CONTEXT_SIZE = 4096
MAX_TOKENS = 2048

# ── Model discovery (borrowed from chat.py) ────────────────────────────────

_PREFERRED_MODELS = [
    r"qwen3[\.\-_]?5",            # Qwen 3.5 — latest & fastest
    r"qwen3(?![\.\-_]?5)",        # Qwen 3
    r"llama-3\.2-3b",             # Llama 3.2 3B — compact
    r"phi-3\.5-mini",             # Phi 3.5 mini
    r"mistral-7b-instruct",       # Mistral 7B
    r"qwen2\.5",                  # Qwen 2.5
]


def find_best_model() -> Optional[Path]:
    """Discover best available GGUF model."""
    if not MODELS_DIR.exists():
        return None

    all_models = sorted(
        [m for m in MODELS_DIR.glob("*.gguf") if m.stat().st_size >= 50_000_000],
        key=lambda m: m.name.lower(),
    )

    if not all_models:
        return None

    # Try preferred patterns
    for pattern in _PREFERRED_MODELS:
        for model in all_models:
            if re.search(pattern, model.name, re.IGNORECASE):
                size_gb = model.stat().st_size / (1024 ** 3)
                log.info(f"Selected: {model.name} ({size_gb:.1f} GB)")
                return model

    # Fallback: smallest model >= 3GB
    balanced = [m for m in all_models if 3 <= m.stat().st_size / (1024 ** 3) <= 15]
    if balanced:
        return min(balanced, key=lambda m: m.stat().st_size)

    return min(all_models, key=lambda m: m.stat().st_size)


class LlamaServer:
    """Manage llama-server subprocess and API calls."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._started_by_us = False
        self._base_url = f"http://127.0.0.1:{LLAMA_PORT}"
        self._session: Optional[httpx.AsyncClient] = None

    async def start(self, model_path: Optional[Path] = None) -> bool:
        """Start llama-server if not already running."""
        if await self._is_running():
            log.info("llama-server already running")
            return True

        if not model_path:
            model_path = find_best_model()
            if not model_path:
                log.error("No GGUF models found in C:/AI/Models")
                return False

        if not SERVER_BIN.exists():
            log.error(f"llama-server.exe not found: {SERVER_BIN}")
            return False

        log.info(f"Starting llama-server with: {model_path.name}")
        try:
            self._proc = subprocess.Popen(
                [
                    str(SERVER_BIN),
                    "-m", str(model_path),
                    "--port", str(LLAMA_PORT),
                    "--ctx-size", str(CONTEXT_SIZE),
                    "--threads", str(max(4, os.cpu_count() or 8)),
                    "-ngl", "100",  # GPU acceleration if available
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._started_by_us = True
            
            # Wait for server to be ready with retry logic
            log.info("Waiting for llama-server to initialize...")
            for attempt in range(15):  # 15 * 1sec = up to 15 seconds
                await asyncio.sleep(1)
                if await self._is_running():
                    log.info("llama-server ready ✓")
                    return True
                if attempt % 3 == 0:
                    log.info(f"  Initializing... ({attempt+1}s)")

            log.error("llama-server initialization timeout")
            return False
        except Exception as e:
            log.error(f"Failed to start server: {e}")
            return False

    async def _is_running(self) -> bool:
        """Check if llama-server is responding."""
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 400
        except Exception:
            return False

    async def transpile(self, py_code: str, func_name: str) -> str:
        """Transpile Python to Rust via OpenAI-compatible endpoint."""
        if not self._session:
            self._session = httpx.AsyncClient(timeout=httpx.Timeout(300.0))

        prompt = f"""Convert this Python to Rust. Output ONLY Rust code, no explanation.
Do NOT use <think> tags. Do NOT explain. Just output Rust code.

```python
{py_code}
```

```rust"""

        try:
            log.info(f"Transpiling: {func_name} (waiting for LLM...)")
            t0 = time.time()
            resp = await self._session.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": "local",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                    "stream": False,
                },
            )
            elapsed = time.time() - t0
            log.info(f"  Response in {elapsed:.1f}s (HTTP {resp.status_code})")
            
            if resp.status_code != 200:
                log.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return ""
                
            data = resp.json()
            
            if "choices" not in data or not data["choices"]:
                log.error(f"No choices in response")
                return ""
                
            rust_code = data["choices"][0]["message"]["content"].strip()

            # Strip <think>...</think> blocks (Qwen3.5 reasoning)
            rust_code = re.sub(r"<think>.*?</think>", "", rust_code, flags=re.DOTALL)
            # Clean up markdown fences
            rust_code = re.sub(r"^```(?:rust)?\n?", "", rust_code, flags=re.MULTILINE)
            rust_code = re.sub(r"\n?```$", "", rust_code, flags=re.MULTILINE)
            return rust_code.strip()

        except httpx.ReadTimeout:
            elapsed = time.time() - t0
            log.error(f"  Timeout after {elapsed:.0f}s — model too slow for this prompt")
            return ""
        except Exception as e:
            log.error(f"Transpile failed for {func_name}: {type(e).__name__}: {e}")
            return ""

    async def close(self):
        """Cleanup."""
        if self._session:
            await self._session.aclose()
        if self._proc and self._started_by_us:
            log.info("Stopping llama-server...")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


async def main():
    """Demo transpiler."""
    server = LlamaServer()

    try:
        if not await server.start():
            return

        print("\n" + "=" * 70)
        print("Python → Rust Transpiler (llama.cpp)")
        print("=" * 70 + "\n")

        examples = {
            "fibonacci": """def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)""",

            "matrix_multiply": """def matrix_multiply(a, b):
    result = [[0] * len(b[0]) for _ in range(len(a))]
    for i in range(len(a)):
        for j in range(len(b[0])):
            for k in range(len(b)):
                result[i][j] += a[i][k] * b[k][j]
    return result""",

            "parse_csv": """def parse_csv(content: str):
    lines = content.strip().split('\\n')
    headers = lines[0].split(',')
    return [dict(zip(headers, line.split(','))) for line in lines[1:]]""",
        }

        for name, code in examples.items():
            print(f"[Python] {name}:")
            print(code)
            print()

            try:
                rust = await server.transpile(code, name)
                print(f"[Rust] {name}:")
                print(rust)
                print("\n" + "-" * 70 + "\n")
            except Exception as e:
                print(f"[ERROR] {e}\n")
                print("-" * 70 + "\n")

    finally:
        await server.close()


if __name__ == "__main__":
    asyncio.run(main())
