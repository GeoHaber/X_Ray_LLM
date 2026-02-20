"""
Core/llm_manager.py — LLM Runtime & Model Manager
====================================================

Detects hardware (CPU / RAM / GPU / OS), manages llama.cpp installation,
and provides a human-readable model catalog so users can pick the best
LLM for their machine.

Usage::

    from Core.llm_manager import LLMManager
    mgr = LLMManager()
    mgr.print_system_profile()
    mgr.check_runtime()        # detect / offer install of llama.cpp
    mgr.recommend_models()     # suggest models based on hardware
    mgr.settings_menu()        # interactive settings
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════
#  1.  Hardware / OS Detection  (vendored from Local_LLM mothership)
# ═══════════════════════════════════════════════════════════════════════════
#  HardwareProfile and detect_hardware() are now the canonical versions
#  from the mothership.  The _mothership/ vendor package is synced via
#  `python <Local_LLM>/tools/mothership_sync.py <X_Ray_root>`.
#
#  Fallback: if _mothership is missing (e.g. fresh clone), a minimal
#  inline HardwareProfile is defined so the rest of the module still works.
# ═══════════════════════════════════════════════════════════════════════════

try:
    from _mothership.hardware_detection import detect_hardware   # noqa: F401
    from _mothership.models import HardwareProfile               # noqa: F401
except ImportError:
    # ── Minimal fallback when _mothership is not vendored yet ──────────
    @dataclass
    class HardwareProfile:                        # type: ignore[no-redef]
        """Minimal fallback — run mothership_sync to get the full version."""
        os_name: str = ""
        os_version: str = ""
        arch: str = ""
        cpu_brand: str = ""
        cpu_cores: int = 1
        ram_gb: float = 0.0
        available_ram_gb: float = 0.0
        gpu_name: str = "none"
        gpu_vram_gb: float = 0.0
        avx2: bool = False
        avx512: bool = False
        neon: bool = False

        @property
        def tier(self) -> str:
            if self.gpu_vram_gb >= 8:
                return "high"
            if self.ram_gb >= 16 and self.avx2:
                return "medium"
            if self.ram_gb >= 8 and self.avx2:
                return "low"
            return "minimal"

        @property
        def tier_label(self) -> str:
            labels = {
                "high":    "🟢 High — GPU offload, large models OK",
                "medium":  "🟡 Medium — 7B–13B models on CPU",
                "low":     "🟠 Low — small 1B–3B models only",
                "minimal": "🔴 Minimal — LLM may be too slow",
            }
            return labels.get(self.tier, "unknown")

        @property
        def recommended_gpu_layers(self) -> int:
            return -1 if self.gpu_vram_gb >= 2 else 0

        @property
        def fingerprint(self) -> str:
            return f"{self.cpu_brand} | {self.gpu_name} | {self.ram_gb:.0f}GB RAM"

        def to_dict(self) -> Dict[str, Any]:
            return {
                "os": f"{self.os_name} {self.os_version}",
                "arch": self.arch,
                "cpu": self.cpu_brand,
                "cores": self.cpu_cores,
                "ram_gb": round(self.ram_gb, 1),
                "gpu": self.gpu_name,
                "gpu_vram_gb": round(self.gpu_vram_gb, 1),
                "avx2": self.avx2,
                "tier": self.tier,
            }

    def detect_hardware() -> HardwareProfile:     # type: ignore[no-redef]
        """Fallback detector — less capable than mothership version."""
        return HardwareProfile(
            os_name=platform.system(),
            os_version=platform.release(),
            arch=platform.machine(),
            cpu_brand=platform.processor() or "Unknown CPU",
            cpu_cores=os.cpu_count() or 1,
            ram_gb=8.0,
            gpu_name="none",
            gpu_vram_gb=0.0,
            avx2=False,
            avx512=False,
            neon="arm" in platform.machine().lower(),
        )




# ═══════════════════════════════════════════════════════════════════════════
#  2.  LLM Model Catalog
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ModelCard:
    """Human-readable model description."""
    id: str                     # e.g. "qwen2.5-coder-7b-q4"
    name: str                   # "Qwen 2.5 Coder 7B"
    family: str                 # "Qwen", "DeepSeek", "Llama", "Phi", "Gemma"
    params: str                 # "7B", "3B", "14B"
    quant: str                  # "Q4_K_M", "Q5_K_M", "Q8_0"
    size_gb: float              # download size
    ram_needed_gb: float        # minimum RAM to run
    vram_needed_gb: float       # VRAM if GPU offloading
    min_tier: str               # "minimal", "low", "medium", "high"

    # ── Human-readable capability summary ──
    speed: str                  # "⚡ Fast", "🏃 Medium", "🐢 Slow"
    code_quality: str           # "★★★★★", "★★★★☆", etc.
    reasoning: str              # "★★★☆☆" etc.
    best_for: str               # one-line description

    # Download info
    gguf_url: str = ""          # direct .gguf download URL (HuggingFace)
    gguf_filename: str = ""     # e.g. "qwen2.5-coder-7b-q4_k_m.gguf"

    @property
    def stars(self) -> str:
        """Summary line: code + reasoning."""
        return f"Code: {self.code_quality}  Reasoning: {self.reasoning}"

    @property
    def human_summary(self) -> str:
        """One-paragraph human-readable card."""
        return (
            f"{self.name} ({self.params}, {self.quant})\n"
            f"  Size: {self.size_gb:.1f} GB download, needs {self.ram_needed_gb:.0f} GB RAM\n"
            f"  Speed: {self.speed}  |  {self.stars}\n"
            f"  Best for: {self.best_for}"
        )


# ── Pre-built catalog of recommended models ──
MODEL_CATALOG: List[ModelCard] = [
    # ── Tiny (minimal tier) ──
    ModelCard(
        id="qwen2.5-coder-1.5b-q4",
        name="Qwen 2.5 Coder 1.5B", family="Qwen", params="1.5B",
        quant="Q4_K_M", size_gb=1.0, ram_needed_gb=4, vram_needed_gb=2,
        min_tier="minimal",
        speed="⚡ Very Fast", code_quality="★★★☆☆", reasoning="★★☆☆☆",
        best_for="Quick code suggestions on weak hardware",
        gguf_filename="qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
    ),
    ModelCard(
        id="phi-3.5-mini-q4",
        name="Phi 3.5 Mini 3.8B", family="Phi", params="3.8B",
        quant="Q4_K_M", size_gb=2.3, ram_needed_gb=6, vram_needed_gb=4,
        min_tier="low",
        speed="⚡ Fast", code_quality="★★★★☆", reasoning="★★★☆☆",
        best_for="Good balance of speed and quality on 8 GB machines",
        gguf_filename="Phi-3.5-mini-instruct-Q4_K_M.gguf",
    ),
    # ── Medium tier ──
    ModelCard(
        id="qwen2.5-coder-7b-q4",
        name="Qwen 2.5 Coder 7B", family="Qwen", params="7B",
        quant="Q4_K_M", size_gb=4.4, ram_needed_gb=10, vram_needed_gb=6,
        min_tier="medium",
        speed="🏃 Medium", code_quality="★★★★★", reasoning="★★★★☆",
        best_for="Best code model for 16 GB RAM — excellent refactoring",
        gguf_filename="qwen2.5-coder-7b-instruct-q4_k_m.gguf",
    ),
    ModelCard(
        id="deepseek-coder-v2-lite-q4",
        name="DeepSeek Coder V2 Lite 16B", family="DeepSeek", params="16B (MoE)",
        quant="Q4_K_M", size_gb=5.5, ram_needed_gb=12, vram_needed_gb=8,
        min_tier="medium",
        speed="🏃 Medium", code_quality="★★★★★", reasoning="★★★★☆",
        best_for="Strong code + reasoning via Mixture-of-Experts",
        gguf_filename="DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M.gguf",
    ),
    ModelCard(
        id="codellama-13b-q4",
        name="Code Llama 13B", family="Llama", params="13B",
        quant="Q4_K_M", size_gb=7.3, ram_needed_gb=16, vram_needed_gb=10,
        min_tier="medium",
        speed="🐢 Slower", code_quality="★★★★☆", reasoning="★★★☆☆",
        best_for="Battle-tested code generation & infilling",
        gguf_filename="codellama-13b-instruct.Q4_K_M.gguf",
    ),
    # ── High tier (GPU needed) ──
    ModelCard(
        id="qwen2.5-coder-32b-q4",
        name="Qwen 2.5 Coder 32B", family="Qwen", params="32B",
        quant="Q4_K_M", size_gb=19, ram_needed_gb=24, vram_needed_gb=20,
        min_tier="high",
        speed="🐢 Slow", code_quality="★★★★★", reasoning="★★★★★",
        best_for="Near-GPT-4 code quality — needs 24 GB+ VRAM",
        gguf_filename="qwen2.5-coder-32b-instruct-q4_k_m.gguf",
    ),
    ModelCard(
        id="deepseek-r1-7b-q4",
        name="DeepSeek R1 Distill 7B", family="DeepSeek", params="7B",
        quant="Q4_K_M", size_gb=4.7, ram_needed_gb=10, vram_needed_gb=6,
        min_tier="medium",
        speed="🏃 Medium", code_quality="★★★★☆", reasoning="★★★★★",
        best_for="Best reasoning model for code refactoring decisions",
        gguf_filename="DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
    ),
    ModelCard(
        id="gemma-2-9b-q4",
        name="Gemma 2 9B", family="Gemma", params="9B",
        quant="Q4_K_M", size_gb=5.5, ram_needed_gb=12, vram_needed_gb=8,
        min_tier="medium",
        speed="🏃 Medium", code_quality="★★★★☆", reasoning="★★★★☆",
        best_for="Google's versatile model — great general + code",
        gguf_filename="gemma-2-9b-it-Q4_K_M.gguf",
    ),
]

TIER_ORDER = {"minimal": 0, "low": 1, "medium": 2, "high": 3}


def recommend_models(hw: HardwareProfile) -> List[ModelCard]:
    """Return models that can run on this hardware, sorted by quality."""
    tier_val = TIER_ORDER.get(hw.tier, 0)
    compatible = []
    for m in MODEL_CATALOG:
        model_tier_val = TIER_ORDER.get(m.min_tier, 4)
        if model_tier_val <= tier_val and m.ram_needed_gb <= hw.ram_gb + 2:
            compatible.append(m)
    # Sort: best code_quality first, then by size (smaller preferred)
    compatible.sort(key=lambda m: (-m.code_quality.count("★"), m.size_gb))
    return compatible


# ═══════════════════════════════════════════════════════════════════════════
#  3.  llama.cpp Runtime Manager
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RuntimeInfo:
    """Status of the llama.cpp runtime."""
    installed: bool
    path: str               # path to llama-server / llama-cli
    version: str            # e.g. "b4532"
    backend: str            # "cpu", "cuda", "metal", "vulkan"
    server_running: bool    # is llama-server currently running?
    server_port: int        # port if running


def detect_runtime() -> RuntimeInfo:
    """Check if llama.cpp (llama-server or llama-cli) is installed."""
    # Search common names
    names = ["llama-server", "llama-cli", "llama.cpp", "server"]
    found_path = ""
    for name in names:
        path = shutil.which(name)
        if path:
            found_path = path
            break
    # Also check common install locations
    if not found_path:
        common_dirs = [
            Path.home() / "llama.cpp" / "build" / "bin",
            Path.home() / "llama.cpp",
            Path("C:/llama.cpp/build/bin"),
            Path("C:/llama.cpp"),
            Path("/usr/local/bin"),
        ]
        for d in common_dirs:
            for name in names:
                p = d / (name + (".exe" if platform.system() == "Windows" else ""))
                if p.exists():
                    found_path = str(p)
                    break
            if found_path:
                break

    if not found_path:
        return RuntimeInfo(
            installed=False, path="", version="",
            backend="none", server_running=False, server_port=0)

    # Get version
    version = _get_runtime_version(found_path)

    # Detect backend from binary
    backend = _detect_backend(found_path)

    # Check if server is already running
    running, port = _check_server_running()

    return RuntimeInfo(
        installed=True,
        path=found_path,
        version=version,
        backend=backend,
        server_running=running,
        server_port=port,
    )


def _get_runtime_version(path: str) -> str:
    """Get llama.cpp version string."""
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10)
        text = result.stdout + result.stderr
        m = re.search(r"b(\d{3,5})", text)
        if m:
            return f"b{m.group(1)}"
        return text.strip()[:50]
    except Exception:
        return "unknown"


def _detect_backend(path: str) -> str:
    """Heuristic: check which backend the llama.cpp binary uses."""
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, text=True, timeout=10)
        text = (result.stdout + result.stderr).lower()
        if "cuda" in text:
            return "cuda"
        if "metal" in text:
            return "metal"
        if "vulkan" in text:
            return "vulkan"
        if "rocm" in text or "hip" in text:
            return "rocm"
    except Exception:
        pass
    return "cpu"


def _check_server_running() -> Tuple[bool, int]:
    """Check if llama-server is already running on common ports."""
    for port in [8080, 5000, 11434]:
        try:
            req = urllib.request.Request(
                f"http://localhost:{port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True, port
        except Exception:
            pass
    return False, 0


# ── Latest release info (cached) ──

_LATEST_RELEASE_URL = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"


def get_latest_release() -> Dict[str, Any]:
    """Fetch the latest llama.cpp release info from GitHub."""
    try:
        req = urllib.request.Request(_LATEST_RELEASE_URL, method="GET")
        req.add_header("Accept", "application/vnd.github.v3+json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "unknown")
            assets = data.get("assets", [])
            # Find Windows/Linux/Mac binaries
            bins = {}
            for a in assets:
                name = a.get("name", "").lower()
                url = a.get("browser_download_url", "")
                if "win" in name and "x64" in name and name.endswith(".zip"):
                    bins["windows-x64"] = url
                elif "win" in name and "arm64" in name:
                    bins["windows-arm64"] = url
                elif "linux" in name and "x64" in name:
                    bins["linux-x64"] = url
                elif "macos" in name or "darwin" in name:
                    bins["macos"] = url
                elif "ubuntu" in name and "x64" in name:
                    bins["linux-x64"] = url
            return {"tag": tag, "binaries": bins}
    except Exception:
        return {"tag": "unknown", "binaries": {}}


# ═══════════════════════════════════════════════════════════════════════════
#  4.  Settings (persisted to xray_settings.json)
# ═══════════════════════════════════════════════════════════════════════════

SETTINGS_FILE = "xray_settings.json"

DEFAULT_SETTINGS = {
    "llm": {
        "runtime": "llama.cpp",          # "llama.cpp", "ollama", "openai-compat"
        "model_id": "",                  # from catalog or custom
        "model_path": "",                # path to .gguf file
        "server_url": "http://localhost:8080/v1",
        "api_key": "sk-placeholder",
        "context_size": 4096,
        "gpu_layers": -1,               # -1 = auto
        "threads": 0,                   # 0 = auto (cpu_count)
        "temperature": 0.7,
        "max_tokens": 1024,
    },
    "scan": {
        "default_mode": "smell+lint+security",
        "exclude_dirs": [],
    },
}


def load_settings(project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load settings from xray_settings.json, merging with defaults."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    paths = []
    if project_dir:
        paths.append(Path(project_dir) / SETTINGS_FILE)
    paths.append(Path.home() / ".xray" / SETTINGS_FILE)
    paths.append(Path(SETTINGS_FILE))

    for p in paths:
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    user = json.load(f)
                _deep_merge(settings, user)
                break
            except Exception:
                pass
    return settings


def save_settings(settings: Dict[str, Any],
                  project_dir: Optional[Path] = None) -> Path:
    """Save settings to xray_settings.json."""
    if project_dir:
        path = Path(project_dir) / SETTINGS_FILE
    else:
        path = Path(SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    return path


def _deep_merge(base: dict, overlay: dict):
    """Recursively merge overlay into base."""
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ═══════════════════════════════════════════════════════════════════════════
#  5.  Unified Manager
# ═══════════════════════════════════════════════════════════════════════════

class LLMManager:
    """All-in-one manager: hardware, runtime, models, settings."""

    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = project_dir
        self.hw: Optional[HardwareProfile] = None
        self.runtime: Optional[RuntimeInfo] = None
        self.settings = load_settings(project_dir)

    def detect_all(self):
        """Detect hardware and runtime in one call."""
        self.hw = detect_hardware()
        self.runtime = detect_runtime()

    # ── Formatted output ──

    def format_system_profile(self) -> str:
        """Return a formatted string of the system profile."""
        if not self.hw:
            self.hw = detect_hardware()
        hw = self.hw
        lines = [
            "",
            "  ┌─────────────────────────────────────────────────────┐",
            "  │          🖥  SYSTEM PROFILE                         │",
            "  ├─────────────────────────────────────────────────────┤",
            f" │  OS:     {hw.os_name} {hw.os_version} ({hw.arch})",
            f" │  CPU:    {hw.cpu_brand}",
            f" │  Cores:  {hw.cpu_cores} logical",
            f" │  RAM:    {hw.ram_gb:.1f} GB",
            f" │  GPU:    {hw.gpu_name}",
        ]
        if hw.gpu_vram_gb > 0:
            lines.append(f" │  VRAM:   {hw.gpu_vram_gb:.1f} GB")
        lines.append(f" │  AVX2:   {'✓' if hw.avx2 else '✗'}   AVX-512: {'✓' if hw.avx512 else '✗'}   NEON: {'✓' if hw.neon else '✗'}")
        lines.append(f" │  Tier:   {hw.tier_label}")
        lines.append("  └─────────────────────────────────────────────────────┘")
        return "\n".join(lines)

    def format_runtime_status(self) -> str:
        """Return a formatted string of the llama.cpp runtime status."""
        if not self.runtime:
            self.runtime = detect_runtime()
        rt = self.runtime
        if not rt.installed:
            return (
                "\n  ⚠  llama.cpp NOT FOUND\n"
                "     Install from: https://github.com/ggerganov/llama.cpp\n"
                "     Or run: X_Ray --interactive → Settings → Install Runtime\n"
            )
        status = "🟢 Running" if rt.server_running else "🔴 Stopped"
        port_info = f" (port {rt.server_port})" if rt.server_running else ""
        return (
            f"\n  ✓ llama.cpp {rt.version}\n"
            f"    Path:    {rt.path}\n"
            f"    Backend: {rt.backend}\n"
            f"    Server:  {status}{port_info}\n"
        )

    def format_model_recommendations(self) -> str:
        """Return formatted model recommendations for this hardware."""
        if not self.hw:
            self.hw = detect_hardware()
        models = recommend_models(self.hw)
        if not models:
            return "\n  ⚠  No compatible models found for your hardware.\n"

        lines = [
            "",
            "  ┌─────────────────────────────────────────────────────┐",
            "  │          🧠 RECOMMENDED MODELS                      │",
            "  ├─────────────────────────────────────────────────────┤",
        ]
        for i, m in enumerate(models[:6], 1):
            tag = " ← BEST FIT" if i == 1 else ""
            lines.append(f"  │")
            lines.append(f"  │  {i}. {m.name} ({m.params}, {m.quant}){tag}")
            lines.append(f"  │     {m.speed}  |  Code: {m.code_quality}  Reasoning: {m.reasoning}")
            lines.append(f"  │     RAM: {m.ram_needed_gb:.0f} GB   Download: {m.size_gb:.1f} GB")
            lines.append(f"  │     {m.best_for}")
        lines.append("  │")
        lines.append("  └─────────────────────────────────────────────────────┘")
        return "\n".join(lines)

    def check_and_prompt(self) -> Dict[str, Any]:
        """Check runtime status and return action recommendations.

        Returns a dict with keys:
            - "runtime_ok": bool
            - "needs_install": bool
            - "needs_upgrade": bool (newer version available)
            - "latest_version": str
            - "models_available": List[ModelCard]
            - "recommended_model": Optional[ModelCard]
        """
        self.detect_all()
        result: Dict[str, Any] = {
            "runtime_ok": self.runtime.installed,
            "needs_install": not self.runtime.installed,
            "needs_upgrade": False,
            "latest_version": "",
            "models_available": [],
            "recommended_model": None,
        }

        # Check for newer version
        if self.runtime.installed:
            latest = get_latest_release()
            result["latest_version"] = latest.get("tag", "")
            if (result["latest_version"] and self.runtime.version
                    and result["latest_version"] != self.runtime.version):
                result["needs_upgrade"] = True

        # Recommend models
        models = recommend_models(self.hw)
        result["models_available"] = models
        if models:
            result["recommended_model"] = models[0]

        return result

    def start_server(self, model_path: str = "",
                     port: int = 8080) -> bool:
        """Start llama-server with the selected model."""
        if not self.runtime or not self.runtime.installed:
            return False

        if not model_path:
            model_path = self.settings["llm"].get("model_path", "")
        if not model_path or not Path(model_path).exists():
            return False

        hw = self.hw or detect_hardware()
        gpu_layers = self.settings["llm"].get("gpu_layers", -1)
        threads = self.settings["llm"].get("threads", 0) or hw.cpu_cores
        ctx = self.settings["llm"].get("context_size", 4096)

        cmd = [
            self.runtime.path,
            "-m", model_path,
            "--port", str(port),
            "-c", str(ctx),
            "-t", str(threads),
        ]
        if gpu_layers != 0 and hw.gpu_vram_gb > 0:
            cmd.extend(["-ngl", str(gpu_layers)])

        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            return False
