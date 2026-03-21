# X-Ray LLM — Best-of-Breed Improvement To-Do

> Benchmarked against: Ruff, Semgrep, SonarQube, CodeRabbit, DeepSource, Snyk, Bandit
> Generated: March 21, 2026

---

## Phase 1: Performance — Make It Faster ⚡

### 1.1 Parallel File Scanning
- [x] Add `concurrent.futures.ProcessPoolExecutor` to `scan_directory()` in `xray/scanner.py`
- [x] Partition files into N batches (N = cpu_count), scan in parallel, merge results
- [x] Add `parallel=True` kwarg (default True) with fallback to sequential
- [ ] **Benchmark**: Target 3-5× speedup on multi-core machines
- **Files**: `xray/scanner.py`

### 1.2 Incremental Scanning with File-Hash Cache
- [x] Add `_ScanCache` class to `xray/scanner.py` that stores `{filepath: {hash, findings}}`
- [x] On re-scan, skip files whose SHA-256 hash hasn't changed
- [x] Add `--incremental` CLI flag to `xray/agent.py`
- [x] Cache stored as `.xray_cache.json` in project root
- [ ] **Benchmark**: Target 10-50× faster on re-scans
- **Files**: `xray/scanner.py`, `xray/agent.py`

### 1.3 Pre-compiled Rule Regex
- [x] Compile all regex patterns at module load time via `_get_compiled()` cache
- [x] Reuse compiled patterns in `scan_file()` instead of re-compiling per call
- **Files**: `xray/scanner.py`

### 1.4 Rust Scanner Rule Parity
- [ ] Implement remaining 10 rules in `scanner/src/rules/mod.rs` (28 → 38)
- [ ] Use `generate_rust_rules.py` to auto-transpile where possible
- [ ] Cross-validate with `python build.py --validate`
- **Files**: `scanner/src/rules/mod.rs`, `generate_rust_rules.py`

---

## Phase 2: Architecture — Make It Maintainable 🏗️

### 2.1 Split God Module `ui_server.py`
- [ ] Create `api/` directory with route modules:
  - `api/__init__.py`, `api/scan_routes.py`, `api/fix_routes.py`
  - `api/analysis_routes.py`, `api/browse_routes.py`, `api/pm_routes.py`
- [ ] Create `services/` directory with business logic:
  - `services/__init__.py`, `services/scan_manager.py`
  - `services/satd_scanner.py`, `services/git_analyzer.py`
- [ ] Keep `ui_server.py` as thin HTTP dispatcher only
- **Files**: `ui_server.py` → `api/`, `services/`

### 2.2 Replace Global State with AppState
- [ ] Create `services/app_state.py` with `AppState` singleton
- [ ] Move all global mutable state behind `threading.RLock()`
- [ ] Replace direct global access in all route modules
- **Files**: `services/app_state.py`, all route modules

### 2.3 Plugin/Rule System
- [ ] Define `RuleSchema` dataclass in `xray/rules/schema.py`
- [ ] Support loading external rules from `~/.xray/rules/` or `--rules-dir`
- [ ] Register fixers via `@fixer("RULE-ID")` decorator pattern
- **Files**: `xray/rules/schema.py`, `xray/fixer.py`

---

## Phase 3: Detection Quality — Make It Smarter 🧠

### 3.1 SARIF Output Format
- [x] Create `xray/sarif.py` with SARIF 2.1.0 schema converter
- [x] Add `--format sarif` to CLI
- [x] Unlocks: GitHub Code Scanning tab, VS Code SARIF Viewer, Azure DevOps
- **Files**: `xray/sarif.py`, `xray/agent.py`

### 3.2 Baseline / Diff Scanning
- [x] Add `--baseline <previous-report.json>` CLI flag
- [x] Compare current findings against baseline, report only net-new issues
- [ ] Add `--since <git-commit>` flag for git-aware diff scanning
- **Files**: `xray/scanner.py`, `xray/agent.py`

### 3.3 SCA (Software Composition Analysis)
- [x] Create `xray/sca.py` integrating `pip-audit` programmatically
- [x] Parse `requirements.txt` / `pyproject.toml` for dependencies
- [x] Merge CVE findings into scan results with severity mapping
- **Files**: `xray/sca.py`

### 3.4 Inline Suppression Comments
- [x] Support `# xray: ignore[RULE-ID]` to suppress findings per-line
- [x] Support `# xray: ignore` to suppress all rules on a line
- [ ] Add `--show-suppressed` CLI flag for auditing
- **Files**: `xray/scanner.py`

### 3.5 AST-Based Detection (Python rules)
- [ ] Add `ast.NodeVisitor` detectors for PY-001 through PY-008
- [ ] Keep regex as fallback for non-Python files
- [ ] Target 30-50% false-positive reduction on Python scanning
- **Files**: `xray/scanner.py`, new `xray/ast_analyzers.py`

---

## Phase 4: Release Engineering — Make It Professional 📦

### 4.1 Docker Containerization
- [x] Create multi-stage `Dockerfile` (Rust builder → Python slim)
- [x] Create `docker-compose.yml` for one-command startup
- **Files**: `Dockerfile`, `docker-compose.yml`

### 4.2 PyPI Publishing Pipeline
- [x] Add `.github/workflows/publish.yml` — publish wheel on tag `v*`
- [x] Sync `__version__` in `xray/__init__.py` to 0.3.0
- **Files**: `.github/workflows/publish.yml`, `xray/__init__.py`

### 4.3 Pre-built Binaries via GitHub Releases
- [x] Add `.github/workflows/release.yml`
- [x] Build Rust scanner for 5 targets on tag push
- [x] Attach binaries to GitHub Release
- **Files**: `.github/workflows/release.yml`

### 4.4 Version Synchronization
- [x] Create `scripts/bump_version.py`
- [x] Updates `pyproject.toml`, `Cargo.toml`, `xray/__init__.py` atomically
- **Files**: `scripts/bump_version.py`

---

## Phase 5: Integrations — Make It Connected 🔌

### 5.1 GitHub PR Integration
- [x] Create `action.yml` GitHub Action
- [x] Scan changed files, post summary via SARIF upload to Code Scanning
- **Files**: `action.yml`

### 5.2 VS Code Extension (lightweight)
- [ ] Create minimal VS Code extension: run xray CLI → parse SARIF → Problems panel
- [ ] Depends on SARIF output (3.1) being done first
- **Files**: `vscode-xray/` directory

### 5.3 MCP Server
- [ ] Create MCP (Model Context Protocol) server for AI agents
- [ ] Expose scan, fix-preview, and analysis as MCP tools
- **Files**: `xray/mcp_server.py`

---

## Phase 6: Developer Experience — Quick Wins 🎯

### 6.1 `__main__.py` Entry Point
- [x] Create `xray/__main__.py` so `python -m xray` works
- **Files**: `xray/__main__.py`

### 6.2 Configuration File Support
- [x] Read `[tool.xray]` from `pyproject.toml` for project settings
- [x] Support: severity, exclude patterns, output format, incremental, parallel
- [x] Fall back to CLI args
- **Files**: `xray/config.py`, `xray/agent.py`

### 6.3 Rich CLI Output
- [ ] Group findings by file with severity color coding
- [ ] Add `--format rich` CLI option
- **Files**: `xray/agent.py`

---

## Priority Matrix

| Item | Priority | Effort | Impact | Status |
|------|----------|--------|--------|--------|
| `__main__.py` (6.1) | **P0** | Trivial | CLI usability | ✅ Done |
| Inline suppression (3.4) | **P0** | Low | Adoption enabler | ✅ Done |
| SARIF output (3.1) | **P0** | Low | Unlocks GitHub + VS Code | ✅ Done |
| Pre-compiled regex (1.3) | **P0** | Low | Scan speed | ✅ Done |
| Config file support (6.2) | **P1** | Low | Per-project config | ✅ Done |
| Parallel scanning (1.1) | **P1** | Medium | 3-5× faster | ✅ Done |
| Incremental cache (1.2) | **P1** | Medium | 10-50× re-scan | ✅ Done |
| Baseline/diff scanning (3.2) | **P1** | Low | CI adoption | ✅ Done |
| SCA integration (3.3) | **P2** | Medium | Feature gap fill | ✅ Done |
| Docker (4.1) | **P2** | Medium | Distribution | ✅ Done |
| PyPI publish (4.2) | **P2** | Low | Distribution | ✅ Done |
| GitHub Releases (4.3) | **P2** | Low | Distribution | ✅ Done |
| Version sync (4.4) | **P2** | Low | Release hygiene | ✅ Done |
| GitHub PR action (5.1) | **P2** | Medium | Team adoption | ✅ Done |
| Split ui_server.py (2.1) | **P2** | High | Maintainability | 🔲 |
| Plugin system (2.3) | **P3** | High | Extensibility | 🔲 |
| AST detection (3.5) | **P3** | High | False-positive reduction | 🔲 |
| Rust rule parity (1.4) | **P3** | Medium | Full Rust path | 🔲 |
| VS Code extension (5.2) | **P3** | High | IDE adoption | 🔲 |
| MCP server (5.3) | **P3** | Medium | AI agent integration | 🔲 |
| Rich CLI (6.3) | **P3** | Low | Polish | 🔲 |

---

*Benchmarked against Ruff (46k★), Semgrep (14k★), SonarQube (10k★), CodeRabbit, DeepSource, Snyk, Bandit*
*Last updated: March 21, 2026*
