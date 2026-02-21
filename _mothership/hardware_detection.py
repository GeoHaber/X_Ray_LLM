"""
Hardware Detection — Zero-dependency system profiling for LLM capacity planning.

Detects CPU brand, total RAM, GPU name + VRAM, AVX2/AVX-512/NEON support,
and classifies the machine into a capability tier so other modules can
automatically recommend compatible models.

Design:
    - ZERO external dependencies — uses only stdlib (ctypes, winreg,
      subprocess, platform).  psutil is *not* required.
    - Cross-platform: Windows, Linux, macOS (Intel + Apple Silicon).
    - Each detector is a standalone function — easy to test in isolation.
    - HardwareProfile lives in Core.models (single source of truth).

Usage::

    from Core.services.hardware_detection import detect_hardware
    hw = detect_hardware()
    print(hw.tier_label)          # "🟡 Medium — 7B–13B models on CPU"
    print(hw.to_dict())           # JSON-safe dict

Author : Local_LLM project (backported from X_Ray)
License: MIT
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .models import HardwareProfile

logger = logging.getLogger(__name__)


# ============================================================================
# CPU
# ============================================================================


def _cpu_brand_windows() -> Optional[str]:
    """Read CPU brand from Windows registry."""
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
    )
    name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
    winreg.CloseKey(key)
    return name.strip()


def _cpu_brand_linux() -> Optional[str]:
    """Read CPU brand from /proc/cpuinfo."""
    with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return None


def _cpu_brand_darwin() -> Optional[str]:
    """Read CPU brand via sysctl."""
    out = subprocess.check_output(
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        text=True,
        timeout=5,
    ).strip()
    return out or None


_CPU_BRAND_DISPATCH = {
    "Windows": _cpu_brand_windows,
    "Linux": _cpu_brand_linux,
    "Darwin": _cpu_brand_darwin,
}


def _detect_cpu_brand() -> str:
    """Best-effort CPU brand string using native OS APIs.

    Windows : winreg (instant, no subprocess)
    Linux   : /proc/cpuinfo
    macOS   : sysctl -n machdep.cpu.brand_string
    Fallback: platform.processor()
    """
    handler = _CPU_BRAND_DISPATCH.get(platform.system())
    if handler:
        try:
            result = handler()
            if result:
                return result
        except Exception as exc:
            logger.debug("CPU brand detection failed: %s", exc)
    return platform.processor() or "Unknown CPU"


# ============================================================================
# RAM
# ============================================================================


def _ram_gb_windows() -> float:
    """Read total RAM via Windows ctypes."""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    return mem.ullTotalPhys / (1024**3)


def _ram_gb_linux() -> Optional[float]:
    """Read total RAM from /proc/meminfo."""
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            if line.startswith("MemTotal"):
                kb = int(re.search(r"\d+", line).group())
                return kb / (1024**2)
    return None


def _ram_gb_darwin() -> float:
    """Read total RAM via sysctl."""
    out = subprocess.check_output(
        ["sysctl", "-n", "hw.memsize"],
        text=True,
        timeout=5,
    ).strip()
    return int(out) / (1024**3)


_RAM_GB_DISPATCH = {
    "Windows": _ram_gb_windows,
    "Linux": _ram_gb_linux,
    "Darwin": _ram_gb_darwin,
}


def _detect_ram_gb() -> float:
    """Detect total physical RAM in GB.

    Windows : ctypes → kernel32.GlobalMemoryStatusEx (no deps)
    Linux   : /proc/meminfo
    macOS   : sysctl -n hw.memsize
    Fallback: 8.0 GB (safe conservative assumption)
    """
    handler = _RAM_GB_DISPATCH.get(platform.system())
    if handler:
        try:
            result = handler()
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("RAM detection failed: %s", exc)
    return 8.0  # conservative fallback


def _avail_ram_gb_windows() -> float:
    """Read available RAM via Windows ctypes."""
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
    return mem.ullAvailPhys / (1024**3)


def _avail_ram_gb_linux() -> Optional[float]:
    """Read available RAM from /proc/meminfo."""
    with open("/proc/meminfo", encoding="utf-8") as f:
        for line in f:
            if line.startswith("MemAvailable"):
                kb = int(re.search(r"\d+", line).group())
                return kb / (1024**2)
    return None


def _avail_ram_gb_darwin() -> float:
    """Estimate available RAM via sysctl (rough: total × 0.5)."""
    out = subprocess.check_output(
        ["sysctl", "-n", "hw.memsize"],
        text=True,
        timeout=5,
    ).strip()
    total = int(out) / (1024**3)
    return total * 0.5


_AVAIL_RAM_DISPATCH = {
    "Windows": _avail_ram_gb_windows,
    "Linux": _avail_ram_gb_linux,
    "Darwin": _avail_ram_gb_darwin,
}


def _detect_available_ram_gb() -> float:
    """Detect available (free) RAM in GB.

    Windows : ctypes → GlobalMemoryStatusEx
    Linux   : /proc/meminfo → MemAvailable
    macOS   : vm_stat + sysctl
    Fallback: total_ram * 0.5
    """
    handler = _AVAIL_RAM_DISPATCH.get(platform.system())
    if handler:
        try:
            result = handler()
            if result is not None:
                return result
        except Exception as exc:
            logger.debug("Available RAM detection failed: %s", exc)
    return _detect_ram_gb() * 0.5


# ============================================================================
# GPU
# ============================================================================


def _detect_gpu_nvidia() -> Optional[Tuple[str, float]]:
    """Try NVIDIA GPU via nvidia-smi."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            parts = out.split(",")
            name = parts[0].strip()
            vram_mb = float(parts[1].strip()) if len(parts) > 1 else 0
            return (f"NVIDIA {name}", vram_mb / 1024)
    except Exception:
        pass
    return None


def _detect_gpu_amd() -> Optional[Tuple[str, float]]:
    """Try AMD GPU via rocm-smi."""
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showmeminfo", "vram"],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
        )
        if "Total" in out:
            m = re.search(r"Total Memory.*?(\d+)", out)
            vram = int(m.group(1)) / (1024**2) if m else 0
            return ("AMD GPU (ROCm)", vram)
    except Exception:
        pass
    return None


def _detect_gpu_apple() -> Optional[Tuple[str, float]]:
    """Try Apple Metal (M-series unified memory)."""
    if platform.system() == "Darwin" and "arm" in platform.machine().lower():
        ram = _detect_ram_gb()
        return (f"Apple {platform.machine()} (Metal)", ram * 0.75)
    return None


def _detect_gpu_wmi() -> Optional[Tuple[str, float]]:
    """Try Windows WMI fallback for Intel UHD, AMD integrated, etc."""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController).Name",
            ],
            text=True,
            timeout=10,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
        ).strip()
        if out:
            names = [n.strip() for n in out.splitlines() if n.strip()]
            discrete = [
                n
                for n in names
                if not any(
                    x in n.lower() for x in ["microsoft basic", "virtual", "remote"]
                )
            ]
            return (discrete[0] if discrete else names[0], 0.0)
    except Exception:
        pass
    return None


def _detect_gpu() -> Tuple[str, float]:
    """Detect GPU name and VRAM in GB.

    Checks in order: NVIDIA → AMD ROCm → Apple Metal → Windows WMI.
    Returns (gpu_name, vram_gb) — ("none", 0.0) if nothing found.
    """
    return (
        _detect_gpu_nvidia()
        or _detect_gpu_amd()
        or _detect_gpu_apple()
        or _detect_gpu_wmi()
        or ("none", 0.0)
    )


# ============================================================================
# INSTRUCTION SET (AVX2, AVX-512, NEON)
# ============================================================================


def _detect_avx() -> Tuple[bool, bool]:
    """Detect AVX2 and AVX-512 support.

    Windows : winreg CPU Identifier → Family/Model heuristic
    Linux   : /proc/cpuinfo flags
    macOS   : sysctl hw.optional.avx*
    """
    system = platform.system()
    avx2 = False
    avx512 = False
    try:
        if system == "Windows":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            ident, _ = winreg.QueryValueEx(key, "Identifier")
            winreg.CloseKey(key)
            # Family 6 model ≥ 60 → Haswell+ → AVX2
            m = re.search(r"Model\s+(\d+)", ident)
            if m:
                model = int(m.group(1))
                avx2 = model >= 60
                avx512 = model >= 85
            return avx2, avx512
        if system == "Linux":
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
            return "avx2" in text, "avx512" in text
        if system == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-a"],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            avx2 = "hw.optional.avx2_0: 1" in out
            avx512 = "hw.optional.avx512" in out and ": 1" in out
            return avx2, avx512
    except Exception as exc:
        logger.debug("AVX detection failed: %s", exc)
    return avx2, avx512


# ============================================================================
# PUBLIC API
# ============================================================================


def detect_hardware() -> HardwareProfile:
    """Auto-detect the full hardware profile of this machine.

    Returns a HardwareProfile dataclass with all fields populated.
    Every sub-detector is wrapped in try/except so this never raises.
    """
    os_name = platform.system()
    os_version = platform.release()
    arch = platform.machine()
    cpu_brand = _detect_cpu_brand()
    cpu_cores = os.cpu_count() or 1
    ram_gb = _detect_ram_gb()
    available_ram_gb = _detect_available_ram_gb()
    gpu_name, gpu_vram = _detect_gpu()
    avx2, avx512 = _detect_avx()
    neon = "aarch64" in arch.lower() or "arm64" in arch.lower()

    hw = HardwareProfile(
        os_name=os_name,
        os_version=os_version,
        arch=arch,
        cpu_brand=cpu_brand,
        cpu_cores=cpu_cores,
        ram_gb=ram_gb,
        available_ram_gb=available_ram_gb,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram,
        avx2=avx2,
        avx512=avx512,
        neon=neon,
    )
    logger.info(
        "Hardware detected: %s, %d cores, %.1f GB RAM, GPU=%s (%.1f GB VRAM), "
        "AVX2=%s, tier=%s",
        cpu_brand,
        cpu_cores,
        ram_gb,
        gpu_name,
        gpu_vram,
        avx2,
        hw.tier,
    )
    return hw


def format_hardware_profile(hw: HardwareProfile, box_width: int = 55) -> str:
    """Render a box-drawing summary of the hardware profile.

    Returns a multi-line string ready for terminal output.
    """
    w = max(box_width, 45)
    inner = w - 4  # space inside │ ... │

    def _line(label: str, value: str) -> str:
        text = f"  {label:<9} {value}"
        return f"  │ {text:<{inner}}│"

    top = f"  ┌{'─' * (w - 2)}┐"
    title = f"  │{'🖥  SYSTEM PROFILE':^{inner}}│"
    sep = f"  ├{'─' * (w - 2)}┤"
    bot = f"  └{'─' * (w - 2)}┘"

    lines = [
        "",
        top,
        title,
        sep,
        _line("OS:", f"{hw.os_name} {hw.os_version} ({hw.arch})"),
        _line("CPU:", hw.cpu_brand),
        _line("Cores:", f"{hw.cpu_cores} logical"),
        _line("RAM:", f"{hw.ram_gb:.1f} GB total, {hw.available_ram_gb:.1f} GB free"),
        _line("GPU:", hw.gpu_name),
    ]
    if hw.gpu_vram_gb > 0:
        lines.append(_line("VRAM:", f"{hw.gpu_vram_gb:.1f} GB"))

    avx_line = (
        f"AVX2: {'✓' if hw.avx2 else '✗'}   "
        f"AVX-512: {'✓' if hw.avx512 else '✗'}   "
        f"NEON: {'✓' if hw.neon else '✗'}"
    )
    lines.append(_line("ISA:", avx_line))
    lines.append(_line("Tier:", hw.tier_label))
    lines.append(bot)
    return "\n".join(lines)
