# X-Ray Features & Test Coverage Registry

> **Purpose**: Single source of truth for *every* feature in X-Ray and its
> corresponding test file(s).  When a new feature is added, update this
> document *in the same commit* as the feature code.  Every item in
> **Section 1** must have a ✅ test file in **Section 2**.

---

## 1 · Feature Inventory

### 1.1 Core Engine (`Core/`)

| Feature | Module | Since | Notes |
|---------|--------|-------|-------|
| CLI argument parsing | `Core/cli_args.py` | v1.0 | `--fix-smells`, `--gen-tests`, etc. |
| Scan context (phases) | `Core/scan_context.py` | v1.0 | 5 scan phases |
| LLM manager | `Core/llm_manager.py` | v3.0 | Ollama / Claude / mock |
| Inference engine | `Core/inference.py` | v2.0 | Function-level type hinting |
| Shared types | `Core/types.py` | v1.0 | `FunctionRecord`, `ClassRecord`, `SmellIssue` |
| Config constants | `Core/config.py` | v1.0 | Thresholds, always-skip dirs |
| Utility helpers | `Core/utils.py` | v1.0 | File helpers, colour output |
| Scan cache | `Core/scan_cache.py` | v5.0 | SHA-based incremental cache |
| Nexus orchestrator | `Core/nexus_orchestrator.py` | v6.0 | Multi-agent mode |

### 1.2 Analysis (`Analysis/`)

| Feature | Module | Since | Notes |
|---------|--------|-------|-------|
| AST utilities | `Analysis/ast_utils.py` | v1.0 | Function/class extraction |
| Code smell detection | `Analysis/smells.py` | v1.0 | 15+ heuristic checks |
| Duplicate detection | `Analysis/duplicates.py` | v1.0 | Token-hash dedup |
| Lint runner | `Analysis/lint.py` | v2.0 | Ruff wrapper |
| Security analysis | `Analysis/security.py` | v3.0 | Bandit wrapper |
| Rust advisor | `Analysis/rust_advisor.py` | v4.0 | Candidate scoring |
| Auto-rustify | `Analysis/auto_rustify.py` | v4.0 | Full Python → Rust pipeline |
| Smart import graph | `Analysis/smart_graph.py` | v5.0 | Module dependency graph |
| Transpiler | `Analysis/transpiler.py` | v4.0 | Python → Rust code gen |
| Library advisor | `Analysis/library_advisor.py` | v5.0 | Package upgrade hints |
| Scan cache | `Analysis/scan_cache.py` | v5.0 | Cache read/write |
| Reporting & grading | `Analysis/reporting.py` | v1.0 | A+→F grade computation |
| **Web smell detector** | `Analysis/web_smells.py` | **v7.0** | JS/TS/React smell detection |
| **Project health checker** | `Analysis/project_health.py` | **v7.0** | Structural completeness score |
| **Smell auto-fixer** | `Analysis/smell_fixer.py` | **v7.0** | `--fix-smells` engine |
| **Test generator** | `Analysis/test_generator.py` | **v7.0** | `--gen-tests` engine |

### 1.3 Language Support (`Lang/`)

| Feature | Module | Since | Notes |
|---------|--------|-------|-------|
| Python AST scanner | `Lang/py_ast.py` | v1.0 | Primary analysis engine |
| Python tokenizer | `Lang/tokenizer.py` | v2.0 | Token-level analysis |
| **JS/TS/JSX/TSX analyzer** | `Lang/js_ts_analyzer.py` | **v7.0** | Regex-based, no tree-sitter |

### 1.4 UI Layer

| Feature | Module | Since | Notes |
|---------|--------|-------|-------|
| CLI print bridge | `ui_bridge.py` | v5.0 | `PrintBridge`, `NullBridge`, `TqdmBridge` |
| Flet desktop UI | `x_ray_flet.py` | v3.0 | Native desktop app |
| Claude markdown UI | `x_ray_claude.py` | v6.0 | Rich markdown output |
| Unified terminal UI | `x_ray_ui.py` | v1.0 | Original terminal mode |

---

## 2 · Test Coverage Map

> ✅ = dedicated test file exists and passes  
> ⚠️ = partial coverage only  
> ❌ = no dedicated tests

### 2.1 Core

| Module | Test File | Status | # Tests |
|--------|-----------|--------|---------|
| `Core/types.py` | `tests/test_core_types.py` | ✅ | 24 |
| `Core/utils.py` | `tests/test_core_utils.py` | ✅ | 18 |
| `Core/inference.py` | `tests/test_core_inference.py` | ✅ | 16 |
| `Core/scan_cache.py` | `tests/test_scan_cache.py` | ✅ | 12 |
| `Core/cli_args.py` | `tests/test_xray_core_comprehensive.py` | ✅ | — |
| `Core/scan_context.py` | `tests/test_xray_core_comprehensive.py` | ⚠️ | phases only |

### 2.2 Analysis

| Module | Test File | Status | # Tests |
|--------|-----------|--------|---------|
| `Analysis/ast_utils.py` | `tests/test_lang_ast.py` | ✅ | 30 |
| `Analysis/smells.py` | `tests/test_analysis_smells.py`, `test_smells_new.py` | ✅ | 60+ |
| `Analysis/duplicates.py` | `tests/test_analysis_duplicates.py` | ✅ | 20 |
| `Analysis/lint.py` | `tests/test_analysis_lint.py` | ✅ | 15 |
| `Analysis/security.py` | `tests/test_analysis_security.py` | ✅ | 20 |
| `Analysis/rust_advisor.py` | `tests/test_analysis_rustadvisor.py` | ✅ | 25 |
| `Analysis/auto_rustify.py` | `tests/xray_generated/test_xray_Analysis_auto_rustify.py` | ✅ | — |
| `Analysis/transpiler.py` | `tests/test_transpiler.py`, `test_llm_transpiler.py` | ✅ | 40+ |
| `Analysis/reporting.py` | `tests/xray_generated/test_xray_Analysis_reporting.py` | ✅ | — |
| **`Analysis/web_smells.py`** | **`tests/test_analysis_web_smells.py`** | **✅** | **40** |
| **`Analysis/project_health.py`** | **`tests/test_analysis_project_health.py`** | **✅** | **45** |
| **`Analysis/smell_fixer.py`** | **`tests/test_analysis_smell_fixer.py`** | **✅** | **34** |
| **`Analysis/test_generator.py`** | **`tests/test_analysis_test_generator.py`** | **✅** | **30** |

### 2.3 Language Support

| Module | Test File | Status | # Tests |
|--------|-----------|--------|---------|
| `Lang/py_ast.py` | `tests/test_lang_ast.py` | ✅ | 30+ |
| `Lang/tokenizer.py` | `tests/test_lang_tokenizer.py` | ✅ | 15 |
| **`Lang/js_ts_analyzer.py`** | **`tests/test_lang_js_ts_analyzer.py`** | **✅** | **50** |

### 2.4 UI

| Module | Test File | Status | # Tests |
|--------|-----------|--------|---------|
| `ui_bridge.py` | `tests/test_ui_bridge.py`, `test_ui_compat.py` | ✅ | 30+ |
| `x_ray_flet.py` | `tests/test_xray_core_comprehensive.py` | ⚠️ | partial |
| `x_ray_claude.py` | `tests/test_xray_claude.py` | ✅ | — |

---

## 3 · Test Suites at a Glance

```
tests/                              # Unit & integration tests
├── test_analysis_*.py              # Per-module Analysis tests
├── test_lang_*.py                  # Per-module Lang tests
├── test_core_*.py                  # Per-module Core tests
├── test_smells_new.py              # Extended smell regression tests
├── test_unified_integration.py     # End-to-end scan pipeline
├── test_monkey_torture.py          # Randomised monkey tests
├── test_semantic_fuzzer.py         # Semantic-level fuzzing
├── test_parity_py_vs_rust.py       # Python ↔ Rust output parity
└── xray_generated/                 # X-Ray auto-generated test stubs
```

**Run all unit tests:**
```bash
pytest tests/ --ignore=tests/xray_generated -q
```

**Run just the v7.0 feature tests:**
```bash
pytest tests/test_lang_js_ts_analyzer.py \
       tests/test_analysis_web_smells.py \
       tests/test_analysis_project_health.py \
       tests/test_analysis_smell_fixer.py \
       tests/test_analysis_test_generator.py -v
```

---

## 4 · Adding a New Feature — Checklist

When you add a **new module** (any file under `Core/`, `Analysis/`, or `Lang/`):

- [ ] Create `tests/test_<package>_<module>.py`
- [ ] Cover: happy path, edge cases (empty input, bad input), class methods, standalone functions
- [ ] Add the module **and** its test file to the table in Section 2
- [ ] Run `pytest tests/ -q` and confirm 0 new failures
- [ ] Commit **both** the feature and its tests in the **same commit**
- [ ] Update the `Since` version column in Section 1

When you add a **new CLI flag / scan phase**:

- [ ] Add to Section 1.1 / 1.2 as appropriate
- [ ] Add integration test in `tests/test_unified_integration.py`
- [ ] Document the flag in `README.md`

---

## 5 · Known Pre-existing Test Failures (as of v7.0)

These 2 failures exist **before** v7.0 and are tracked but not yet fixed:

| Test | File | Issue |
|------|------|-------|
| `test_magic_number_in_full_detector` | `test_smells_new.py` | Smell threshold mismatch |
| `test_dead_code_in_full_detector` | `test_smells_new.py` | Dead code heuristic too strict |

---

## 6 · Version History of Key Feature Additions

| Version | Key Additions |
|---------|--------------|
| v1.0 | Core engine, Python AST scan, smell detection, grading |
| v2.0 | Lint integration (Ruff), inference engine |
| v3.0 | LLM manager (Ollama/Claude), Flet desktop UI |
| v4.0 | Rust advisor, auto-rustify pipeline, transpiler |
| v5.0 | Smart import graph, scan cache, library advisor, Nexus mode |
| v6.0 | Nexus orchestrator, Claude markdown UI, UI bridge protocol |
| **v7.0** | **JS/TS/JSX/TSX scanner, web smells, project health, smell auto-fixer, test generator** |
