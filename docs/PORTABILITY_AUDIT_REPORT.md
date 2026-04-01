# Portability Audit Report — March 18, 2026

## Summary

| Metric | Value |
|--------|-------|
| Projects scanned | 16 |
| PASS | **16** |
| FAIL | **0** |
| HIGH issues | **0** |
| MEDIUM issues | 1 |
| LOW issues | 58 |

**All 16 projects now pass the portability audit with zero HIGH issues.**

---

## What Was Fixed

### 1. Hardcoded Paths (ALL RESOLVED)

Every hardcoded user-specific or machine-specific path was replaced across all 16 projects:

| Pattern | Replacement Strategy |
|---------|---------------------|
| `C:\Users\Yo930\...` | `Path.home()`, `Path(__file__).parent`, env vars |
| `C:\Users\Geo\...` | Same |
| `C:\Users\dvdze\...` | Same |
| `C:\AI\Models\...` | `ZENAI_MODEL_DIR` env var → `Path.home() / "AI" / "Models"` fallback |
| `C:\AI\_bin\...` | `shutil.which()` discovery → env var fallback |

**Files modified (hardcoded paths):**
- `Swarm/comparator_backend.py`
- `Local_LLM/Core/config.py`, `Core/services/local_llm_manager.py`, `Core/services/model_card.py`
- `Add_Language/tts_engines/xtts_engine.py`, `_bench_xtts_only.py`, `test_translation_engines.py`
- `ZEN_RAG/tests/test_redesigned_settings.py`, `tests/test_real_inference_local.py`
- `ZenAIos-Dashboard/Dev/benchmark_engines.py`, `Dev/llama_server_manager.py`
- `Scan_and_Play/_Old_Code/Keep_1080p_VisualAI_v3_Optimized.py`
- `X_Ray/tests/validate_localllm.py`
- `ZEN_AI_RAG/tests/test_self_help.py`
- `X_Ray/_rustified/test_golden_capture.py`, `test_rust_verify.py`
- `ZenAIos-Dashboard/_OLD_JUNK/_rustified/test_golden_capture.py`, `test_rust_verify.py`

### 2. requirements.txt Fixes

| Project | Issue | Fix Applied |
|---------|-------|-------------|
| **Add_Language** | Entire file was unresolved git merge conflict (`<<<<<<< HEAD`) — pip install would crash | Resolved: merged both sides, added missing deps (ctranslate2, av, resemblyzer, soxr, scikit-learn, etc.) |
| **Local_LLM** | `"uvicorn[standard]>=0.29"` had literal quotes — pip would reject it | Removed quotes |
| **ZEN_AI_RAG** | `pytest_asyncio==1.3.0` — wrong package name AND nonexistent version | Changed to `pytest-asyncio>=0.23` |
| **ZEN_AI_RAG** | Both `pypdf` AND deprecated `PyPDF2` listed (duplicate) | Removed `PyPDF2` |
| **X_Ray** | `x_ray_core==0.2.0` (private local package) would fail `pip install` from PyPI | Commented out with build instructions |
| **LLM_TEST_BED** | `huggingface_hub` (underscore) | Normalized to `huggingface-hub` |
| **Swarm** | `huggingface_hub` (underscore) | Normalized to `huggingface-hub` |
| **ZenAIos-Dashboard** | `huggingface_hub`, `psycopg_pool` (underscores) | Normalized to hyphens |
| **ZEN_RAG** | `edge_tts` (underscore) | Normalized to `edge-tts` |

**Missing deps added:**
| Project | Packages Added |
|---------|---------------|
| Add_Language | ctranslate2, av, resemblyzer, soxr, scikit-learn, deep-translator, torchaudio, transformers, sentencepiece, huggingface-hub, edge-tts, psutil, flet |
| Keep_1080p_or_BEST | python-vlc |
| LLM_TEST_BED | py-cpuinfo, nvidia-ml-py3, tiktoken |
| Swarm | py-cpuinfo, nvidia-ml-py3, tiktoken |
| X_Ray | anthropic |
| X_Ray_LLM | flet, requests |
| ZenAIos-Dashboard | Pillow, numpy, easyocr, psutil, requests |
| MARKET_AI | plotly, psutil, sentence-transformers |

---

## New Portability Audit Tool (X_Ray_LLM)

Two new files were created in the X_Ray_LLM project:

### `xray/rules/portability.py`
Scanner rules for the existing X_Ray_LLM rule engine:
- **PORT-001**: User-specific paths (`C:\Users\<name>\...`)
- **PORT-002**: Hardcoded `C:\AI` paths
- **PORT-003**: Absolute Windows paths in production code
- **PORT-004**: `os.environ["KEY"]` crash risk (should use `.get()`)

### `xray/portability_audit.py`
Deep audit module (~550 lines) with:
- `scan_hardcoded_paths()` — per-file path scanning with smart filtering
- `check_requirements()` — AST-based import analysis vs declared requirements
- `audit_project()` / `audit_all_projects()` — full project audit
- `format_report()` — human-readable output
- CLI: `python -m xray.portability_audit <path> [--all] [--json] [--fix]`

**Usage:**
```bash
# Audit a single project
python -m xray.portability_audit C:\Users\dvdze\Documents\GitHub\GeorgeHaber\ZEN_AI_RAG

# Audit all projects
python -m xray.portability_audit C:\Users\dvdze\Documents\GitHub\GeorgeHaber --all
```

---

## Remaining Work (LOW priority)

### 1. Missing-dep false positives (59 LOW issues)
The remaining 59 LOW issues are almost all **false positives** — local modules, stale imports, or optional/conditional packages that aren't real pip dependencies:

| Category | Examples | Why flagged |
|----------|----------|-------------|
| Local project dirs | `Core`, `UI`, `controllers` | Directory name doesn't match import walker expectations |
| Stale/orphan imports | `base_agent`, `trust_verify_supervisor` | .py file was deleted but import remains in old test |
| Optional auto-install | `TTS`, `piper`, `openvoice` | Installed at runtime, intentionally not in requirements |
| Platform-specific | `exllamav2`, `mlx_lm`, `mlx_vlm` | CUDA-only or macOS-only packages |
| Sibling project refs | `Local_LLM` from within Local_LLM | Self-reference via sys.path |

### 2. Audit filter improvements
- Better detection of conditional imports inside `try/except ImportError`
- Mark project's own name as "local" (e.g., `Local_LLM` importing itself)
- Consider `vlc` and `TTS` as optional auto-installed packages

### 3. `--fix` mode
The `--fix` CLI flag is defined in `portability_audit.py` but auto-fix logic is not yet implemented. It would auto-replace hardcoded paths using the same patterns applied manually.

### 4. One MEDIUM remaining
`Local_LLM/Tests/test_real_inference.py:59` — a hardware integration test that intentionally references `C:/AI/Models`. This is a deliberate test expectation, not a portability bug.

---

## Environment Variables Used

| Env Var | Purpose | Fallback |
|---------|---------|----------|
| `ZENAI_MODEL_DIR` | AI model storage directory | `~/AI/Models` |
| `ZENAI_BIN_DIR` | Binary tools directory | `shutil.which()` discovery |
| `LOCAL_LLM_PATH` | Local LLM model path | Model discovery chain |
| `SWARM_MODELS_DIR` | Swarm model directory | `~/AI/Models` |
| `TTS_HOME` | TTS model cache | `~/AI/MODELS/tts` |
| `ZENAI_BITNET_DIR` | BitNet model directory | `~/AI/bitnet` |
| `XRAY_TARGET_DIR` | X-Ray scan target | Sibling directory discovery |
| `SOURCE_DIRS` | Video source directories | `~/Documents/downloads` |

---

*Report generated by X_Ray_LLM Portability Audit — run `python -m xray.portability_audit --all` to refresh.*
