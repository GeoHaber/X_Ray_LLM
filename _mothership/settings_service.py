"""
Settings Service — Persistent JSON configuration with deep-merge.

Manages a settings file (``local_llm_settings.json``) that stores user
preferences such as model paths, server URLs, generation parameters,
and hardware overrides.  Consumer projects copy this module or import
it directly from the Local_LLM mothership.

Design:
    - Settings file is searched in multiple locations (project dir,
      home dir, cwd) — first found wins.
    - Deep-merge: user overrides only the keys they set; everything
      else stays at defaults.
    - save() / load() are pure functions — no singletons.
    - Thread-safe: file writes use a temp-file + rename pattern.

Usage::

    from Core.services.settings_service import load_settings, save_settings

    settings = load_settings()
    settings["llm"]["model_path"] = "C:/AI/Models/qwen2.5-coder-7b.gguf"
    save_settings(settings)

Author : Local_LLM project
License: MIT
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# FILE NAME & DEFAULTS
# ============================================================================

SETTINGS_FILENAME = "local_llm_settings.json"

DEFAULT_SETTINGS: Dict[str, Any] = {
    "llm": {
        "runtime": "llama.cpp",              # "llama.cpp" | "ollama" | "openai-compat"
        "model_id": "",                      # catalog model id or custom
        "model_path": "",                    # path to .gguf file
        "server_url": "http://localhost:8001/v1",
        "api_key": "sk-placeholder",
        "context_size": 4096,
        "gpu_layers": -1,                   # -1 = auto-detect
        "threads": 0,                       # 0 = auto (os.cpu_count)
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 2048,
    },
    "models": {
        "directory": "",                     # empty → use DEFAULT_MODELS_DIR
        "auto_discover": True,
        "min_size_mb": 50,
    },
    "hardware": {
        "gpu_layers_override": None,         # None = auto
        "threads_override": None,            # None = auto
        "tier_override": None,               # None = auto-detect
    },
}


# ============================================================================
# DEEP MERGE
# ============================================================================

def _deep_merge(base: Dict, overlay: Dict) -> Dict:
    """Recursively merge *overlay* into *base* (in-place). Returns base."""
    for key, value in overlay.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ============================================================================
# SEARCH PATHS
# ============================================================================

def _settings_search_paths(project_dir: Optional[Path] = None) -> List[Path]:
    """Return candidate paths for the settings file, ordered by priority."""
    paths: List[Path] = []
    if project_dir:
        paths.append(Path(project_dir) / SETTINGS_FILENAME)
    # Home directory
    home_dir = Path.home() / ".local_llm"
    paths.append(home_dir / SETTINGS_FILENAME)
    # Current working directory (fallback)
    paths.append(Path(SETTINGS_FILENAME))
    return paths


# ============================================================================
# PUBLIC API
# ============================================================================

def load_settings(project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load settings, merging user overrides on top of defaults.

    Searches for the settings file in:
        1. ``<project_dir>/local_llm_settings.json``
        2. ``~/.local_llm/local_llm_settings.json``
        3. ``./local_llm_settings.json``

    Returns a fully-populated dict (defaults + user overrides).
    """
    # Start with a deep copy of defaults
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))

    for path in _settings_search_paths(project_dir):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    user = json.load(f)
                _deep_merge(settings, user)
                logger.debug("Loaded settings from %s", path)
                return settings
            except Exception as exc:
                logger.warning("Failed to load settings from %s: %s", path, exc)

    logger.debug("No settings file found — using defaults")
    return settings


def save_settings(
    settings: Dict[str, Any],
    project_dir: Optional[Path] = None,
) -> Path:
    """Save settings to disk.

    Writes to ``<project_dir>/local_llm_settings.json`` if *project_dir*
    is given, otherwise to ``~/.local_llm/local_llm_settings.json``.

    Uses atomic temp-file + rename to prevent corruption.

    Returns the Path written to.
    """
    if project_dir:
        target = Path(project_dir) / SETTINGS_FILENAME
    else:
        target = Path.home() / ".local_llm" / SETTINGS_FILENAME

    target.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to temp, then rename
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent), suffix=".tmp", prefix="settings_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        # On Windows, os.replace is atomic within the same volume
        os.replace(tmp_path, str(target))
        logger.info("Settings saved to %s", target)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return target


def get_setting(
    settings: Dict[str, Any],
    *keys: str,
    default: Any = None,
) -> Any:
    """Safely navigate nested settings dict.

    Example::

        url = get_setting(settings, "llm", "server_url", default="http://localhost:8001/v1")
    """
    current = settings
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def update_setting(
    settings: Dict[str, Any],
    *keys_and_value,
) -> None:
    """Set a nested value in the settings dict.

    The last positional argument is the value; all preceding arguments
    are dict keys.

    Example::

        update_setting(settings, "llm", "model_path", "/path/to/model.gguf")
    """
    if len(keys_and_value) < 2:
        raise ValueError("Need at least one key and one value")
    keys = keys_and_value[:-1]
    value = keys_and_value[-1]

    current = settings
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value
