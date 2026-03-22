# X-Ray LLM Testing Guide

## Test Suite Overview

X-Ray has **1013 automated tests** (999 passing, 14 skipped) across 22 test files, covering:

- **Unit tests** — scanner rules, fixers, analyzers, API routes
- **Integration tests** — HTTP server, agent loop, services
- **End-to-end tests** — full workflows with real files (95 tests in `test_e2e_real.py`)
- **Edge cases** — empty files, binary files, unicode, deeply nested dirs, 50-file projects
- **Quality assurance** — does-no-harm (SHA-256 verification), regressions, false positives

### What the E2E Suite Covers (95 tests)

**test_e2e_real.py** uses *no mocks or stubs*. Real execution only:

1. **Scanner Integration** (11 tests)
   - All vulnerability types detected
   - Clean files produce no findings
   - File counting
   - Exclude patterns
   - Performance (50-file project < 30s)
   - Unicode filenames, deeply nested dirs

2. **Fixer Integration** (7 tests)
   - Preview and apply fixes
   - SEC-003, QUAL-001, PY-007 deterministic fixes verified
   - Bulk fix operations
   - Non-existent file graceful handling

3. **Agent Loop Integration** (5 tests)
   - Real agent runs with `AgentConfig` + `XRayAgent`
   - Dry-run verification (no file changes)
   - Severity filtering (HIGH-only)
   - Exclude patterns
   - Empty project handling

4. **API Routes** (46 tests)
   - HTTP server bootstrap
   - Scan endpoints (start, progress, result, abort)
   - Fix endpoints (preview, apply)
   - Analysis endpoints (19 analysis tools)
   - PM Dashboard endpoints (9 features)
   - Chat endpoint
   - Error handling

5. **Services** (4 tests)
   - Scan manager (file counting, browse, drives)
   - SATD scanner (TODO/FIXME detection)
   - Chat engine
   - Git import analyzer

6. **SARIF Output** (3 tests)
   - Real scan → SARIF conversion
   - JSON roundtrip validation
   - Empty findings handling

7. **Config Integration** (2 tests)
   - Default values
   - pyproject.toml loading

8. **Analyzer Functions** (11 tests)
   - Code smells, duplicates, dead code, unused imports
   - Architecture maps, call graphs, circular calls
   - Coupling analysis
   - Health scoring
   - Remediation time estimation
   - Test stub generation
   - AI code detection
   - Confidence meter
   - Sprint batches
   - Project review

9. **Rules Integrity** (6 tests)
   - 42 rules total
   - Unique rule IDs
   - Valid regex patterns
   - Valid severity levels
   - Correct ID prefixes
   - Each rule fires on sample code (including JavaScript rules on `.js` files)

10. **Full Workflow** (2 tests)
    - Scan → analyze → fix → rescan shows improvement
    - Scan → SARIF pipeline validation

## Running Tests

### Run All Tests

```bash
python -m pytest tests/ -v
```

**Expected result:** ~999 passed, 14 skipped (platform-specific, external, false-positive regression tests)

### Run Only E2E Tests

```bash
python -m pytest tests/test_e2e_real.py -v
```

**Expected result:** 95 passed

### Run Specific Test Class

```bash
python -m pytest tests/test_e2e_real.py::TestScannerIntegration -v
```

### Run with Coverage

```bash
pip install pytest-cov
python -m pytest tests/ --cov=xray --cov=analyzers --cov=services --cov=api
```

### Run Self-Scan (Quality Assurance)

```bash
python -m pytest tests/test_verify.py -v
```

This verifies:
- Scanning **never modifies** files (SHA-256 verification)
- All 42 rules fire on their sample patterns
- Edge cases handled (binary, empty, symlinks)

## Test File Organization

| File | Tests | Purpose |
|------|------:|---------|
| `test_agent_loop.py` | 12 | Agent SCAN→TEST→FIX→VERIFY→LOOP, AgentConfig, AgentReport |
| `test_analyzers.py` | 25 | All 11 analyzer modules: health, smells, graph, connections, detection |
| `test_build.py` | 35 | Rust build system, cross-compilation, binary discovery |
| `test_compat.py` | 58 | Python/dependency/API/PyPI freshness checker |
| `test_compat_stress.py` | 64 | Stress & edge cases for compat checker |
| `test_comprehensive.py` | 107 | Broad coverage: rules, scanner accuracy, false-positive avoidance |
| `test_config.py` | 26 | XRayConfig defaults, pyproject.toml loading, validation |
| `test_connection_analyzer.py` | 22 | API endpoint & external connection detection |
| `test_e2e_real.py` | 95 | **E2E (no mocks):** scanner, fixer, agent, all 46 API routes, services, SARIF, analyzers, rules, workflow |
| `test_false_positives.py` | 25 | String/comment-aware scanning; known false-positive regression |
| `test_fixer.py` | 14 | 7 deterministic fixers + LLM fallback; preview vs apply |
| `test_fixer_regression.py` | 22 | Fixer regression suite — no fix must break valid code |
| `test_http_integration.py` | 24 | HTTP server bootstrap, all 46 REST endpoint responses |
| `test_llm_mock.py` | 20 | LLM inference mock — deterministic fixer fallback |
| `test_monkey.py` | 158 | Monkey-patch stress tests; edge cases for all 42 rules |
| `test_portability.py` | 20 | PORT-001–004 rules: os.path, platform, encoding, line endings |
| `test_sarif.py` | 24 | SARIF output schema, roundtrip, empty/partial findings |
| `test_sca.py` | 14 | Software composition analysis (pip-audit integration) |
| `test_scanner_boundary.py` | 77 | Scanner boundary: nested dirs, excludes, unicode, symlinks |
| `test_ui_paths.py` | 40 | Path normalization, directory browsing, HTML escaping, dotfile filtering |
| `test_verify.py` | 84 | Does-no-harm (SHA-256 check), finds-real-bugs, binary/huge-file edge cases |
| `test_xray.py` | 47 | Rule database integrity (42 rules), scanner accuracy, language detection |
| **Total** | **1013** | **999 passing, 14 skipped** |

## Skipped Tests (14)

Tests are skipped if:
- Platform-specific (Windows/Linux/macOS only) — 3 tests
- Requires external project (not in repo) — 4 tests
- Rust scanner not built — 1 test
- False-positive edge cases (intentionally skipped) — 4 tests
- Fixer regression (deterministic fixes only) — 2 tests

## Key Test Patterns

### Pattern: No Mocks in test_e2e_real.py

Every test uses real:
- File I/O (`scan_directory()`, `scan_file()`)
- HTTP server (`XRayHandler + HTTPServer`)
- Agents (`AgentConfig` + `XRayAgent`)
- Services (`scan_manager`, `chat_engine`, etc.)

No `unittest.mock.patch()` or `mocker` fixtures.

### Pattern: Fixtures for Temp Projects

```python
@pytest.fixture
def vuln_project(tmp_path):
    """Create temp project with known vulnerabilities."""
    (tmp_path / "vuln.py").write_text("subprocess.run(cmd, shell=True)", encoding="utf-8")
    return tmp_path

def test_scan(vuln_project):
    result = scan_directory(str(vuln_project))
    assert len(result.findings) > 0
```

### Pattern: Real HTTP Testing

```python
@pytest.fixture(scope="module")
def server():
    """Start real HTTP server on free port."""
    srv = _TestServer(("127.0.0.1", 0), XRayHandler)
    # ... bootstrapping
    yield host, port
    srv.shutdown()

def test_api(server):
    status, data, _ = _get(server, "/api/info")
    assert status == 200
```

## Continuous Integration

CI runs on every push:

```bash
# Check
ruff check . && ruff format --check .

# Test
python -m pytest tests/ -v

# Security
python -m bandit -r xray/ -ll

# Self-scan
python -m xray.agent . --dry-run --severity HIGH
```

All must pass before merge.

## Adding New Tests

1. **Unit test** — add to `test_xray.py` or appropriate `test_*.py`
2. **Integration test** — add to `test_http_integration.py` or `test_e2e_real.py`
3. **Analyzer test** — add to `test_analyzers.py`
4. **Fixer test** — add to `test_fixer.py`
5. **API test** — add to `test_e2e_real.py` or `test_http_integration.py`

All new tests:
- Must pass locally: `pytest tests/test_*.py -v`
- Must not use `# type: ignore` without justification
- Must have docstrings
- Should follow existing patterns (fixtures, assertions)

---

**Last updated:** 2026-03-21  
**Test count:** 999 passed, 14 skipped
