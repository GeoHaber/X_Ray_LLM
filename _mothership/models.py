"""
Data Models for Local LLM

Single source of truth for all shared types.
Service modules import from here — no duplicate definitions.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# ENUMS - Categories and Types
# ============================================================================


class ModelCategory(Enum):
    """Model size/performance categories"""

    FAST = "fast"  # <2B params, <1GB
    BALANCED = "balanced"  # 2-13B params, 1-8GB
    LARGE = "large"  # >13B params, >8GB
    SPECIALIZED = "specialized"


class QuantizationType(Enum):
    """GGUF quantization types"""

    Q2_K = "Q2_K"
    Q3_K = "Q3_K"
    Q4_K = "Q4_K"
    Q4_1 = "Q4_1"
    Q5_K = "Q5_K"
    Q5_1 = "Q5_1"
    Q6_K = "Q6_K"
    Q8_0 = "Q8_0"
    F16 = "F16"
    F32 = "F32"


class WorkerRole(Enum):
    """Role in execution pattern"""

    PARALLEL = "parallel"  # Share results equally
    SWARM = "swarm"  # Competitive, best result wins
    COIT = "coit"  # Independent task, don't care about order
    FALLBACK = "fallback"  # Try models in sequence until success


# ============================================================================
# CAPABILITIES
# ============================================================================


@dataclass
class ModelCapabilities:
    """Model capabilities/tags"""

    chat: bool = False
    coding: bool = False
    reasoning: bool = False
    math: bool = False
    multilingual: bool = False
    vision: bool = False

    def to_list(self) -> List[str]:
        """Convert to list of capability names"""
        caps = []
        if self.chat:
            caps.append("Chat")
        if self.coding:
            caps.append("Coding")
        if self.reasoning:
            caps.append("Reasoning")
        if self.math:
            caps.append("Math")
        if self.multilingual:
            caps.append("Multilingual")
        if self.vision:
            caps.append("Vision")
        return caps


# ============================================================================
# HARDWARE PROFILE
# ============================================================================


@dataclass
class HardwareProfile:
    """System hardware profile for LLM capacity planning.

    Detected automatically by ``Core.services.hardware_detection.detect_hardware()``.
    The ``tier`` property classifies the machine so other modules can
    recommend compatible models without manual configuration.
    """

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

    # ------------------------------------------------------------------
    # Tier classification
    # ------------------------------------------------------------------

    @property
    def tier(self) -> str:
        """Capability tier: ``minimal`` | ``low`` | ``medium`` | ``high``.

        Rules:
            - **high** : ≥ 8 GB VRAM  (GPU offload for 7B–13B+ models)
            - **medium**: < 8 GB VRAM but ≥ 16 GB RAM + AVX2  (CPU-only up to 13B)
            - **low**   : 8–15 GB RAM + AVX2                   (small quants only)
            - **minimal**: everything else                      (tiny models only)
        """
        if self.gpu_vram_gb >= 8:
            return "high"
        if self.ram_gb >= 16 and self.avx2:
            return "medium"
        if self.ram_gb >= 8 and self.avx2:
            return "low"
        return "minimal"

    @property
    def tier_label(self) -> str:
        """Human-readable tier description."""
        labels = {
            "high": "\U0001f7e2 High   — GPU offload, 7B-13B+ models",
            "medium": "\U0001f7e1 Medium — 7B-13B models on CPU",
            "low": "\U0001f7e0 Low    — small quants (Q2-Q4), ≤7B",
            "minimal": "\U0001f534 Minimal — tiny models only (≤1B)",
        }
        return labels.get(self.tier, self.tier)

    @property
    def recommended_gpu_layers(self) -> int:
        """Auto-compute ``n_gpu_layers`` for llama.cpp.

        Logic absorbed from swarm_test's ``load_hardware_config()``:
            - NVIDIA / AMD discrete → ``-1`` (full offload)
            - Integrated / no GPU    → ``0``  (CPU only)
        """
        gpu = self.gpu_name.lower()
        # NVIDIA discrete
        if any(
            k in gpu for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")
        ):
            return -1
        # AMD discrete with ROCm
        if any(k in gpu for k in ("radeon rx", "radeon pro", "rocm")):
            return -1
        # Apple Metal — unified memory, treat as GPU-capable
        if "metal" in gpu or self.neon:
            return -1
        return 0

    @property
    def fingerprint(self) -> str:
        """One-line hardware summary for logs and benchmark metadata."""
        return f"{self.cpu_brand} | {self.gpu_name} | {self.ram_gb:.0f}GB RAM"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "os_name": self.os_name,
            "os_version": self.os_version,
            "arch": self.arch,
            "cpu_brand": self.cpu_brand,
            "cpu_cores": self.cpu_cores,
            "ram_gb": round(self.ram_gb, 2),
            "available_ram_gb": round(self.available_ram_gb, 2),
            "gpu_name": self.gpu_name,
            "gpu_vram_gb": round(self.gpu_vram_gb, 2),
            "avx2": self.avx2,
            "avx512": self.avx512,
            "neon": self.neon,
            "tier": self.tier,
            "tier_label": self.tier_label,
            "recommended_gpu_layers": self.recommended_gpu_layers,
            "fingerprint": self.fingerprint,
        }


# ============================================================================
# LLAMA.CPP STATUS
# ============================================================================


@dataclass
class LlamaCppStatus:
    """Status of llama.cpp installation and runtime"""

    installed: bool
    version: Optional[str] = None
    latest_version: Optional[str] = None
    needs_update: bool = False
    path: Optional[str] = None
    running: bool = False
    port: int = 8001
    pid: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        return {
            "installed": self.installed,
            "version": self.version,
            "latest_version": self.latest_version,
            "needs_update": self.needs_update,
            "path": str(self.path) if self.path else None,
            "running": self.running,
            "port": self.port,
            "pid": self.pid,
            "error": self.error,
        }


# ============================================================================
# MODEL CARD  (canonical — the rich version from model_card.py)
# ============================================================================


@dataclass
class ModelCard:
    """Complete model metadata for display"""

    id: str  # Unique identifier
    name: str  # Display name
    filename: str  # Actual filename
    path: Path  # Full path to file
    size: str  # Formatted size (e.g. "~4GB")
    size_bytes: int  # Actual size in bytes
    base_model: str  # Base model name (e.g. "mistral-7b")
    quantization: Optional[str]  # Quantization type
    category: ModelCategory  # Performance category
    context: int  # Context window size
    estimated_speed: int  # Estimated tokens/sec
    recommended_ram: int  # Recommended RAM in GB
    description: str  # Short description
    capabilities: ModelCapabilities  # What it can do
    source: str  # Source repo
    url: str  # Download/info URL
    version: Optional[str] = None  # Model version
    release_date: Optional[str] = None  # Release date
    last_updated: Optional[str] = None  # Last update date

    def to_card_dict(self) -> dict:
        """Convert to UI card dict"""
        return {
            "id": self.id,
            "name": self.name,
            "filename": self.filename,
            "size": self.size,
            "base_model": self.base_model,
            "quantization": self.quantization,
            "category": self.category.value,
            "context": self.context,
            "estimated_speed": self.estimated_speed,
            "recommended_ram": self.recommended_ram,
            "description": self.description,
            "capabilities": self.capabilities.to_list(),
            "source": self.source,
            "url": self.url,
            "version": self.version,
            "path": str(self.path),
        }

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict (alias for backward compat)"""
        return self.to_card_dict()


# ============================================================================
# INFERENCE TYPES  (unified — used by both engine and async workers)
# ============================================================================


@dataclass
class EngineInferenceRequest:
    """Request for the in-memory inference engine (FIFOLlamaCppInference)."""

    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    stream: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineInferenceResult:
    """Result from the in-memory inference engine."""

    text: str
    chunks: List[str] = field(default_factory=list)
    model_name: str = ""
    latency: float = 0.0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerInferenceRequest:
    """Request for async worker patterns (parallel, swarm, COIT)."""

    request_id: str
    prompt: str
    model_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # Higher = more urgent
    timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerInferenceResult:
    """Result from async worker patterns."""

    request_id: str
    model_name: str
    response: str
    tokens: int
    latency: float
    success: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerStats:
    """Statistics for a worker"""

    model_name: str
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    avg_latency: float = 0.0
    peak_latency: float = 0.0
    min_latency: float = float("inf")
    total_tokens: int = 0


# ============================================================================
# REQUESTS/RESPONSES (discovery)
# ============================================================================


@dataclass
class DiscoverModelsRequest:
    """Request to discover available models"""

    search_paths: List[Path] = field(default_factory=list)
    recursive: bool = True
    include_subdirs: bool = True


@dataclass
class DiscoverModelsResponse:
    """Response with discovered models"""

    models: List[ModelCard] = field(default_factory=list)
    total_count: int = 0
    total_size_gb: float = 0.0
    duplicates: Dict[str, List[ModelCard]] = field(default_factory=dict)
    status: str = "success"
    error: Optional[str] = None


@dataclass
class LocalLLMStatus:
    """Complete local LLM infrastructure status"""

    llama_cpp_ready: bool
    llama_cpp_status: Optional[LlamaCppStatus] = None
    models_discovered: int = 0
    models: List[ModelCard] = field(default_factory=list)
    duplicate_groups: Optional[Dict[str, List[ModelCard]]] = None
    hardware: Optional[HardwareProfile] = None
    status: str = "success"
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict"""
        llama_dict = None
        if self.llama_cpp_status is not None:
            if isinstance(self.llama_cpp_status, dict):
                llama_dict = self.llama_cpp_status
            else:
                llama_dict = self.llama_cpp_status.to_dict()
        return {
            "llama_cpp_ready": self.llama_cpp_ready,
            "llama_cpp_status": llama_dict,
            "models_discovered": self.models_discovered,
            "models": [
                m.to_card_dict() if hasattr(m, "to_card_dict") else m.to_dict()
                for m in self.models
            ],
            "duplicate_groups": {
                k: [
                    m.to_card_dict() if hasattr(m, "to_card_dict") else m.to_dict()
                    for m in v
                ]
                for k, v in (self.duplicate_groups or {}).items()
            },
            "hardware": self.hardware.to_dict() if self.hardware else None,
            "status": self.status,
            "error": self.error,
        }


def fingerprint(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def recommended_gpu_layers(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def tier(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def tier_label(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def to_card_dict(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def to_dict(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")


def to_list(*args, **kwargs):
    raise NotImplementedError("Use ModelCategory directly")
