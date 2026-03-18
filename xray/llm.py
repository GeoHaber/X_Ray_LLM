"""
X-Ray LLM Engine — Local inference via llama-cpp-python.
Generates tests, fixes, and analysis from scan findings.
"""

import os
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMConfig:
    """Configuration for the local LLM."""
    model_path: str = ""
    n_ctx: int = 8192
    n_gpu_layers: int = -1  # -1 = offload all layers to GPU
    temperature: float = 0.3  # low temp for code generation
    max_tokens: int = 2048
    top_p: float = 0.9
    repeat_penalty: float = 1.1

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load config from environment variables."""
        def _int(key: str, default: str) -> int:
            try:
                return int(os.environ.get(key, default))
            except (ValueError, TypeError):
                return int(default)

        def _float(key: str, default: str) -> float:
            try:
                return float(os.environ.get(key, default))
            except (ValueError, TypeError):
                return float(default)

        return cls(
            model_path=os.environ.get("XRAY_MODEL_PATH", ""),
            n_ctx=_int("XRAY_N_CTX", "8192"),
            n_gpu_layers=_int("XRAY_GPU_LAYERS", "-1"),
            temperature=_float("XRAY_TEMPERATURE", "0.3"),
            max_tokens=_int("XRAY_MAX_TOKENS", "2048"),
        )


class LLMEngine:
    """Wrapper around llama-cpp-python for code generation tasks."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        self._model = None
        self._lock = threading.Lock()

    def _ensure_model(self):
        """Lazy-load the model on first use (thread-safe)."""
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            if not self.config.model_path:
                raise RuntimeError(
                    "No model path set. Set XRAY_MODEL_PATH env var or pass LLMConfig.\n"
                    "Recommended models:\n"
                    "  - Qwen2.5-Coder-32B-Instruct-Q4_K_M.gguf (best quality)\n"
                    "  - DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf (fastest)\n"
                    "  - Codestral-22B-v0.1-Q4_K_M.gguf (good balance)"
                )
            from llama_cpp import Llama  # lazy import
            self._model = Llama(
                model_path=self.config.model_path,
                n_ctx=self.config.n_ctx,
                n_gpu_layers=self.config.n_gpu_layers,
                verbose=False,
            )

    def generate(self, prompt: str, system: str = "", max_tokens: int | None = None) -> str:
        """Generate text from a prompt using the local model."""
        self._ensure_model()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._model.create_chat_completion(
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            top_p=self.config.top_p,
            repeat_penalty=self.config.repeat_penalty,
        )
        return response["choices"][0]["message"]["content"]

    def generate_test(self, finding: dict, source_context: str) -> str:
        """Generate a pytest test for a specific finding."""
        system = (
            "You are an expert security and quality test engineer. "
            "Generate a single, focused pytest test function for the described issue. "
            "Return ONLY the Python test function code, no explanation. "
            "Use descriptive test names. Include necessary imports at the top."
        )
        prompt = (
            f"Generate a pytest test for this code issue:\n\n"
            f"Rule: {finding['rule_id']} ({finding['severity']})\n"
            f"Issue: {finding['description']}\n"
            f"File: {finding['file']} line {finding['line']}\n"
            f"Test hint: {finding['test_hint']}\n\n"
            f"Source context:\n```\n{source_context}\n```\n\n"
            f"Write a pytest test function that verifies this issue is fixed."
        )
        return self.generate(prompt, system=system)

    def generate_fix(self, finding: dict, source_context: str,
                     test_error: str = "") -> str:
        """Generate a code fix for a specific finding."""
        system = (
            "You are an expert programmer. Fix the described code issue. "
            "Return ONLY the corrected code snippet that replaces the problematic code. "
            "Keep changes minimal — fix only the issue described. "
            "Do not add comments explaining the fix."
        )
        prompt = (
            f"Fix this code issue:\n\n"
            f"Rule: {finding['rule_id']} ({finding['severity']})\n"
            f"Issue: {finding['description']}\n"
            f"Fix hint: {finding['fix_hint']}\n"
            f"File: {finding['file']} line {finding['line']}\n\n"
            f"Current code:\n```\n{source_context}\n```\n"
        )
        if test_error:
            prompt += (
                f"\nThe previous fix attempt failed with this test error:\n"
                f"```\n{test_error}\n```\n"
                f"Please fix the code so the test passes."
            )
        return self.generate(prompt, system=system)

    def analyze_codebase(self, findings_summary: str) -> str:
        """Generate a high-level analysis of scan results."""
        system = (
            "You are a senior security auditor. Analyze the scan findings and provide "
            "a brief executive summary: what are the most critical issues, what patterns "
            "do you see, and what should be fixed first. Be concise."
        )
        return self.generate(findings_summary, system=system)

    @property
    def is_available(self) -> bool:
        """Check if a model is configured and loadable."""
        if not self.config.model_path:
            return False
        return Path(self.config.model_path).exists()

    def unload(self):
        """Release the model from memory."""
        self._model = None
