"""
X-Ray LLM Engine — Pluggable inference backends.
Generates tests, fixes, and analysis from scan findings.

Supported backends:
  - zen_core  : ZenAI llama-server (managed) via zen_core_libs   [PREFERRED for local]
  - gguf      : Direct GGUF models via llama-cpp-python (in-process, legacy)
  - openai    : OpenAI API (requires openai package + OPENAI_API_KEY)
  - anthropic : Anthropic API (requires anthropic package + ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GGML type enum values for KV cache quantization (used by GGUFBackend).
# ---------------------------------------------------------------------------
GGML_KV_TYPES: dict[str, int] = {
    "f16": 1,
    "q8_0": 8,
    "q5_1": 7,
    "q5_0": 6,
    "q4_1": 3,
    "q4_0": 2,
}


def _resolve_kv_type(value: str) -> int | None:
    """Convert a KV cache type name or integer string to its GGML enum value."""
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    name = value.strip().lower()
    if name in GGML_KV_TYPES:
        return GGML_KV_TYPES[name]
    raise ValueError(
        f"Unknown KV cache type '{value}'. "
        f"Valid names: {', '.join(GGML_KV_TYPES)}  or raw int."
    )


# ═══════════════════════════════════════════════════════════════════════════
# LLMConfig — kept intact for backward compatibility
# ═══════════════════════════════════════════════════════════════════════════

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
    # KV cache quantization
    type_k: int | None = None
    type_v: int | None = None
    flash_attn: bool = False

    @classmethod
    def from_env(cls) -> LLMConfig:
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
            type_k=_resolve_kv_type(os.environ.get("XRAY_TYPE_K", "")),
            type_v=_resolve_kv_type(os.environ.get("XRAY_TYPE_V", "")),
            flash_attn=os.environ.get("XRAY_FLASH_ATTN", "").lower()
            in ("1", "true", "yes"),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Abstract backend protocol
# ═══════════════════════════════════════════════════════════════════════════

class LLMBackend(ABC):
    """Abstract base class that every LLM backend must implement."""

    # Subclasses should set these
    backend_type: str = "unknown"

    @abstractmethod
    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        """Generate a completion for *prompt* and return the text."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return True when the backend is ready to generate."""

    @property
    def backend_name(self) -> str:
        """Human-readable backend identifier, e.g. 'ollama (qwen2.5-coder:7b)'."""
        return self.backend_type


# ═══════════════════════════════════════════════════════════════════════════
# GGUF backend — wraps the original llama-cpp-python code
# ═══════════════════════════════════════════════════════════════════════════

class GGUFBackend(LLMBackend):
    """Local GGUF inference via llama-cpp-python.

    Preserves every env var the original LLMEngine honoured:
      XRAY_MODEL_PATH, XRAY_N_CTX, XRAY_GPU_LAYERS, XRAY_TEMPERATURE,
      XRAY_MAX_TOKENS, XRAY_TYPE_K, XRAY_TYPE_V, XRAY_FLASH_ATTN.
    """

    backend_type = "gguf"

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        self._model = None
        self._lock = threading.Lock()

    @property
    def backend_name(self) -> str:
        model_path = self.config.model_path or "(no model)"
        return f"gguf ({model_path})"

    def _ensure_model(self):
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
            try:
                from llama_cpp import Llama  # lazy import
            except ImportError:
                raise ImportError(
                    "llama-cpp-python is required for GGUF backend. "
                    "Install with: pip install llama-cpp-python"
                )

            kwargs: dict = {
                "model_path": self.config.model_path,
                "n_ctx": self.config.n_ctx,
                "n_gpu_layers": self.config.n_gpu_layers,
                "verbose": False,
                "flash_attn": self.config.flash_attn,
            }
            if self.config.type_k is not None:
                kwargs["type_k"] = self.config.type_k
            if self.config.type_v is not None:
                kwargs["type_v"] = self.config.type_v
            self._model = Llama(**kwargs)

    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        self._ensure_model()
        messages = [{"role": "user", "content": prompt}]
        response = self._model.create_chat_completion(
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            top_p=self.config.top_p,
            repeat_penalty=self.config.repeat_penalty,
        )
        return response["choices"][0]["message"]["content"]

    @property
    def is_available(self) -> bool:
        if not self.config.model_path:
            return False
        return Path(self.config.model_path).exists()

    def unload(self):
        """Release the model from memory."""
        self._model = None


# ═══════════════════════════════════════════════════════════════════════════
# ZenCore backend — uses zen_core_libs LlamaServerManager + LocalLLMAdapter
# This is the PREFERRED local backend. It manages the llama-server process
# lifecycle and uses the same optimized stack as the rest of the monorepo.
# ═══════════════════════════════════════════════════════════════════════════

class ZenCoreBackend(LLMBackend):
    """ZenAI local LLM backend via zen_core_libs.

    Uses :class:`LlamaServerManager` for process lifecycle and
    :class:`LocalLLMAdapter` for HTTP inference.  Shares the same
    optimised llama-server stack (KV cache quantisation, flash attention,
    mlock, continuous batching) as the rest of the monorepo.

    If the server is already running, connects to it.
    If not, auto-starts it with the configured model.
    """

    backend_type = "zen_core"

    def __init__(
        self,
        model_path: str = "",
        port: int = 8001,
        gpu_layers: int = -1,
        ctx_size: int = 8192,
    ):
        self.model_path = model_path or os.environ.get("XRAY_MODEL_PATH", "")
        self.port = port
        self.gpu_layers = gpu_layers
        self.ctx_size = ctx_size
        self._manager = None
        self._adapter = None
        self._started = False

    @property
    def backend_name(self) -> str:
        model_name = Path(self.model_path).stem if self.model_path else "auto"
        return f"zen_core ({model_name} @ port {self.port})"

    def _ensure_running(self):
        """Connect to existing server or start a new one."""
        if self._adapter is not None and self._adapter.check_health():
            return

        try:
            from zen_core_libs.llm import LocalLLMAdapter
        except ImportError:
            raise ImportError(
                "zen_core_libs is required for the zen_core backend.\n"
                "It should be available in the monorepo workspace.\n"
                "Install with:  pip install -e ../zen_core_libs"
            )

        # Reset singleton so we can set our port
        LocalLLMAdapter.reset()
        self._adapter = LocalLLMAdapter(f"http://127.0.0.1:{self.port}")

        # Check if server is already running
        if self._adapter.check_health():
            log.info("Connected to existing llama-server on port %d", self.port)
            return

        # Auto-start the server
        if not self.model_path:
            # Try auto-discover
            from zen_core_libs.llm import discover_models, pick_default_model
            models = discover_models()
            if models:
                best = pick_default_model(models)
                if best:
                    self.model_path = best["path"]
                    log.info("Auto-discovered model: %s (%.1f GB)", best["name"], best["size_gb"])

        if not self.model_path:
            raise RuntimeError(
                "No model available for zen_core backend.\n"
                "Set XRAY_MODEL_PATH or place .gguf files in ~/AI/Models/"
            )

        try:
            from zen_core_libs.llm import LlamaServerManager
        except ImportError:
            raise ImportError("zen_core_libs.llm.LlamaServerManager not available")

        self._manager = LlamaServerManager()
        log.info("Starting llama-server with %s ...", Path(self.model_path).name)
        self._manager.start(
            model_path=self.model_path,
            port=self.port,
            gpu_layers=self.gpu_layers,
            ctx_size=self.ctx_size,
        )
        self._started = True

        # Re-connect adapter after server start
        LocalLLMAdapter.reset()
        self._adapter = LocalLLMAdapter(f"http://127.0.0.1:{self.port}")

    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        self._ensure_running()
        result = self._adapter.generate_text(
            prompt=prompt,
            system_prompt="You are a careful software quality and security engineer.",
            max_tokens=max_tokens,
        )
        # LocalLLMAdapter returns "Brain Offline" if server is down
        if result in ("Brain Offline", "Brain Offline (Start ZenAI)"):
            raise RuntimeError("zen_core llama-server is not responding")
        return result

    @property
    def is_available(self) -> bool:
        # Check if zen_core_libs is importable
        try:
            from zen_core_libs.llm import LocalLLMAdapter  # noqa: F401
        except ImportError:
            return False

        # Check if server is already running OR if we have a model to start one
        try:
            from zen_core_libs.llm import LocalLLMAdapter as Adapter
            Adapter.reset()
            adapter = Adapter(f"http://127.0.0.1:{self.port}")
            if adapter.check_health():
                Adapter.reset()
                return True
            Adapter.reset()
        except Exception:
            pass

        # Can we start one? Need a model path
        if self.model_path and Path(self.model_path).exists():
            return True

        # Try auto-discover
        try:
            from zen_core_libs.llm import discover_models, pick_default_model
            models = discover_models()
            return bool(models and pick_default_model(models))
        except Exception:
            return False

    def unload(self):
        """Stop the server if we started it."""
        if self._manager and self._started:
            self._manager.stop()
            self._started = False
        self._adapter = None


# ═══════════════════════════════════════════════════════════════════════════
# OpenAI backend
# ═══════════════════════════════════════════════════════════════════════════

class OpenAIBackend(LLMBackend):
    """OpenAI API backend.  Requires ``pip install openai`` and OPENAI_API_KEY."""

    backend_type = "openai"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        temperature: float = 0.3,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.temperature = temperature

    @property
    def backend_name(self) -> str:
        return f"openai ({self.model})"

    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "The 'openai' package is required for the OpenAI backend.\n"
                "Install it with:  pip install openai"
            )
        client = openai.OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    @property
    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic backend
# ═══════════════════════════════════════════════════════════════════════════

class AnthropicBackend(LLMBackend):
    """Anthropic API backend.  Requires ``pip install anthropic`` and ANTHROPIC_API_KEY."""

    backend_type = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        temperature: float = 0.3,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.temperature = temperature

    @property
    def backend_name(self) -> str:
        return f"anthropic ({self.model})"

    def generate(self, prompt: str, max_tokens: int = 2048) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "The 'anthropic' package is required for the Anthropic backend.\n"
                "Install it with:  pip install anthropic"
            )
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
        )
        # response.content is a list of ContentBlock; grab the first text block.
        return response.content[0].text if response.content else ""

    @property
    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# Backend factory
# ═══════════════════════════════════════════════════════════════════════════

def create_backend(backend_type: str = "auto", **kwargs) -> LLMBackend:
    """Instantiate an LLM backend by name.

    Args:
        backend_type: ``"zen_core"`` | ``"gguf"`` | ``"openai"`` | ``"anthropic"`` | ``"auto"``
        **kwargs: forwarded to the chosen backend constructor.

    ``"auto"`` tries backends in order:
      1. ZenCore — zen_core_libs managed llama-server (preferred for local)
      2. GGUF   — direct llama-cpp-python in-process (legacy fallback)
      3. OpenAI — if ``OPENAI_API_KEY`` is set
      4. Anthropic — if ``ANTHROPIC_API_KEY`` is set
    """
    import sys as _sys

    backend_type = backend_type.lower().strip()

    if backend_type == "zen_core":
        return ZenCoreBackend(**{k: v for k, v in kwargs.items()
                                if k in ("model_path", "port", "gpu_layers", "ctx_size")})
    elif backend_type == "gguf":
        return GGUFBackend(**{k: v for k, v in kwargs.items() if k == "config"})
    elif backend_type == "openai":
        return OpenAIBackend(**kwargs)
    elif backend_type == "anthropic":
        return AnthropicBackend(**kwargs)
    elif backend_type == "auto":
        reasons: list[str] = []

        # 1. ZenCore (preferred — same LLM stack as the rest of the monorepo)
        zen_kwargs = {k: v for k, v in kwargs.items()
                      if k in ("model_path", "port", "gpu_layers", "ctx_size")}
        zen = ZenCoreBackend(**zen_kwargs)
        if zen.is_available:
            return zen
        reasons.append("zen_core (zen_core_libs not installed or no models found)")

        # 2. GGUF (direct in-process fallback)
        gguf = GGUFBackend(**{k: v for k, v in kwargs.items() if k == "config"})
        if gguf.is_available:
            return gguf
        reasons.append("gguf (no XRAY_MODEL_PATH)" if not gguf.config.model_path
                       else f"gguf (model file not found: {gguf.config.model_path})")

        # 3. OpenAI
        openai_be = OpenAIBackend(
            **{k: v for k, v in kwargs.items() if k in ("model", "api_key", "temperature")}
        )
        if openai_be.is_available:
            return openai_be
        if not openai_be.api_key:
            reasons.append("openai (no OPENAI_API_KEY)")
        else:
            reasons.append("openai (openai package not installed)")

        # 4. Anthropic
        anthropic_be = AnthropicBackend(
            **{k: v for k, v in kwargs.items() if k in ("model", "api_key", "temperature")}
        )
        if anthropic_be.is_available:
            return anthropic_be
        if not anthropic_be.api_key:
            reasons.append("anthropic (no ANTHROPIC_API_KEY)")
        else:
            reasons.append("anthropic (anthropic package not installed)")

        # Nothing available — log diagnostics and return ZenCore
        # (will give clear error when actually used)
        print(f"LLM auto-detection: {', '.join(reasons)}", file=_sys.stderr)
        print("No LLM backend available. Set XRAY_MODEL_PATH or install zen_core_libs.", file=_sys.stderr)
        return zen
    else:
        raise ValueError(
            f"Unknown backend type '{backend_type}'. "
            f"Choose from: zen_core, gguf, openai, anthropic, auto"
        )


def list_backends() -> str:
    """Return a human-readable listing of all backends with their status."""
    lines = ["Available LLM Backends:"]

    # ZenCore (preferred)
    zen = ZenCoreBackend()
    if zen.is_available:
        status = f"available - {zen.backend_name}"
    else:
        try:
            from zen_core_libs.llm import LocalLLMAdapter  # noqa: F401
            status = "installed but no models found - place .gguf in ~/AI/Models/"
        except ImportError:
            status = "not installed - pip install -e ../zen_core_libs"
    lines.append(f"  zen_core    ZenAI managed llama-server (preferred)   [{status}]")

    # GGUF (legacy)
    gguf = GGUFBackend()
    if gguf.is_available:
        status = f"available - {gguf.config.model_path}"
    else:
        status = "not configured - set XRAY_MODEL_PATH"
    lines.append(f"  gguf        Direct GGUF via llama-cpp-python         [{status}]")

    # OpenAI
    openai_be = OpenAIBackend()
    if openai_be.is_available:
        status = f"available - {openai_be.model}"
    else:
        if not openai_be.api_key:
            status = "not configured - set OPENAI_API_KEY"
        else:
            status = "not configured - pip install openai"
    lines.append(f"  openai      OpenAI API                               [{status}]")

    # Anthropic
    anthropic_be = AnthropicBackend()
    if anthropic_be.is_available:
        status = f"available - {anthropic_be.model}"
    else:
        if not anthropic_be.api_key:
            status = "not configured - set ANTHROPIC_API_KEY"
        else:
            status = "not configured - pip install anthropic"
    lines.append(f"  anthropic   Anthropic API                            [{status}]")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# LLMEngine — high-level wrapper (backward-compatible public API)
# ═══════════════════════════════════════════════════════════════════════════

class LLMEngine:
    """Wrapper around an :class:`LLMBackend` for code generation tasks.

    Fully backward compatible with the original llama-cpp-python-only engine.
    If no *backend* is supplied the constructor falls back to :class:`GGUFBackend`
    using an optional :class:`LLMConfig`, preserving the original behaviour.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        backend: LLMBackend | None = None,
    ):
        if backend is not None:
            self._backend = backend
        else:
            # Legacy path: build a GGUF backend from config / env.
            self._backend = GGUFBackend(config=config or LLMConfig.from_env())

    # -- core generation ---------------------------------------------------

    def generate(self, prompt: str, system: str = "", max_tokens: int | None = None) -> str:
        """Generate text from a prompt.

        ``system`` is prepended to the prompt for backends that don't support
        a native system-message role (all except GGUF chat completion already
        embed it).
        """
        effective_prompt = f"{system}\n\n{prompt}" if system else prompt
        return self._backend.generate(
            effective_prompt,
            max_tokens=max_tokens or 2048,
        )

    # -- higher-level helpers (unchanged) ----------------------------------

    def generate_test(self, finding: dict, source_context: str) -> str:
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

    def generate_fix(self, finding: dict, source_context: str, test_error: str = "") -> str:
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
        system = (
            "You are a senior security auditor. Analyze the scan findings and provide "
            "a brief executive summary: what are the most critical issues, what patterns "
            "do you see, and what should be fixed first. Be concise."
        )
        return self.generate(findings_summary, system=system)

    @property
    def is_available(self) -> bool:
        """Check if the active backend is ready to generate."""
        return self._backend.is_available

    def unload(self):
        """Release the model from memory (GGUF only)."""
        if hasattr(self._backend, "unload"):
            self._backend.unload()
