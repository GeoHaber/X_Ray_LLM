# LLM Model Benchmark for Rust Compile Error Fixing

Evaluates local GGUF models on their ability to fix Rust compilation errors from
Python-to-Rust transpilation. Measures **speed**, **accuracy**, and **code quality**.

## Quick Start

```bash
# Run full benchmark (all available models)
python benchmarks/run_benchmark.py

# Test specific models
python benchmarks/run_benchmark.py --models "Qwen2.5-Coder-14B,Gemma-4-E4B"

# With warmup (reduces first-inference variance)
python benchmarks/run_benchmark.py --warmup

# Validate test cases without running
python benchmarks/run_benchmark.py --validate
```

## Files

| File | Purpose |
|------|---------|
| `run_benchmark.py` | Main benchmark runner |
| `test_cases.json` | Test cases (errors + expected fixes) |
| `results/` | Auto-generated JSON results per run |

## Test Cases (`test_cases.json`)

Each test case represents a real Rust compile error from transpilation:

```json
{
  "id": "E0308_type_mismatch",
  "name": "E0308: type mismatch (usize -> String)",
  "category": "type_error",
  "difficulty": "easy",
  "error_code": "E0308",
  "error_message": "mismatched types: expected `String`, found `usize`",
  "file": "utils.rs",
  "line": 43,
  "context": ">>>0043 |     items.len()\n   0044 | }",
  "expected_patterns": ["to_string()", "format!"],
  "anti_patterns": ["as String"],
  "explanation": "Why this error occurs and the correct fix"
}
```

### Adding New Test Cases

1. Edit `test_cases.json`
2. Add a new entry to the `cases` array
3. Run `python benchmarks/run_benchmark.py --validate` to check format
4. Fields:
   - `expected_patterns`: list of strings that a correct response should contain (any match = pass)
   - `anti_patterns`: strings that indicate a wrong fix (overrides expected_patterns)
   - `difficulty`: `easy` (1x), `medium` (1.5x), `hard` (2x) score weight

## Scoring

Each model gets three scores (0-100):

| Score | Weight | Description |
|-------|--------|-------------|
| **Accuracy** | 60% | % of test cases with correct fix (weighted by difficulty) |
| **Speed** | 25% | Average response time (5s = 100, 60s = 0) |
| **Quality** | 15% | Follows instructions (code-only, no markdown, concise) |

**Combined** = 0.6 * Accuracy + 0.25 * Speed + 0.15 * Quality

## Adding New Models

Edit the `MODELS` dict in `run_benchmark.py`:

```python
MODELS = {
    "My-New-Model": "my-new-model-Q4_K_M.gguf",
    ...
}
```

Or drop any `.gguf` file into `C:\AI\Models` (or `--models-dir`).

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ZENAI_LLAMA_SERVER` | Path to `llama-server` binary (e.g., `C:\AI\_bin\llama-server.exe`) |
| `SWARM_MODELS_DIR` | Directory containing GGUF model files (e.g., `C:\AI\Models`) |
| `ZENAI_MODEL_PATH` | Default model path (optional, for single-model runs) |

## CLI Options

```
--models          Comma-separated model names (default: all available)
--models-dir      GGUF directory (env: SWARM_MODELS_DIR, default: C:\AI\Models)
--test-cases      Custom test cases JSON path
--port            llama-server port (default: 8095)
--ctx-size        Context size tokens (default: 4096)
--timeout         Server startup timeout (default: 180s)
--warmup          Send warmup prompt before testing
--validate        Check test case format only
--output          Custom output JSON path
--backend         Compute backend: auto, cpu, vulkan (default: auto)
```

## Hardware Support

The benchmark auto-detects and reports CPU, GPU, and NPU hardware. Supports:

- **CPU**: AMD Zen4 (AVX512), Zen3 (AVX2), Intel
- **GPU**: AMD Radeon (Vulkan), NVIDIA (Vulkan/CUDA via llama.cpp)
- **NPU**: AMD XDNA (detected but not yet used by llama.cpp)

Use `--backend` to select compute target:
- `auto` — GPU offload if available (default)
- `vulkan` — Force Vulkan GPU backend (AMD/NVIDIA)
- `cpu` — CPU-only, no GPU layers

## Requirements

- `llama-server` (llama.cpp b8639+) in PATH, env var, or at `C:\AI\_bin\llama-server.exe`
- Python 3.10+ with `requests` package
- GGUF model files in `--models-dir`

## Example Output

```
FINAL COMPARISON  (4 models, 8 tests, 342s total)

#   Model                     Size  Accuracy  Avg(s)   Score  Speed  Combined
-------------------------------------------------------------------
1  Qwen2.5-Coder-14B         8.4G      88%    12.1s    85.0   87.2      86.1 *
2  Qwen3.5-9B                5.3G      75%    10.5s    72.0   90.0      78.3
3  Gemma-4-E4B               4.6G      63%     8.2s    60.0   94.2      70.5
4  DeepSeek-R1-14B           8.4G      75%    25.3s    72.0   63.1      69.4
```
