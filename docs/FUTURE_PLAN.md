# X-Ray — Future Plan & Roadmap

## Current Version: 5.0.0

### What's Implemented

**Phase 1 — Diagnose:**
- [x] AST-based code scanning with parallel execution
- [x] 12+ code smell categories with severity levels (CRITICAL / WARNING / INFO)
- [x] 4-stage duplicate detection (exact hash → structural hash → token n-gram → semantic)
- [x] Ruff linter integration (subprocess + JSON parsing)
- [x] Bandit security scanner integration (subprocess + JSON parsing)
- [x] Unified grading formula (A+ → F from 0–100 score)
- [x] Library extraction advisor
- [x] Interactive HTML graph with health-colored nodes
- [x] Full JSON reporting for CI/CD
- [x] Optional LLM enrichment (async + sync)
- [x] 500+ comprehensive tests

**Phase 2 — Cure (Rustify):**
- [x] PyO3 Rust extension module (`x_ray_core`)
- [x] 8 functions ported to Rust (tokenizer, similarity, batch)
- [x] Rayon-based parallel batch processing
- [x] Transparent Python fallback (`try: import x_ray_core`)
- [x] Golden-file parity verification harness
- [x] 10–50× speedup on duplicate detection pipeline
- [x] Transpilation test harness (Python → Rust → compile → verify)

---

## Roadmap

### v5.1 — Rustification Toolkit (Next)

- [ ] **Auto-candidate selection** — X-Ray automatically identifies the best Rust candidates from scan results
- [ ] **Rust code generation** — LLM-assisted Python → Rust transpilation with PyO3 boilerplate
- [ ] **Parity test generator** — Auto-generate golden-file tests for any ported function
- [ ] **Benchmark report** — Integrated Python vs Rust timing comparison in the JSON report
- [ ] **Rust coverage tracking** — Show which functions have Rust acceleration and which don't

### v5.2 — Multi-Language Support

- [ ] **JavaScript/TypeScript** — extend AST parsing to JS/TS via tree-sitter
- [ ] **Rust source analysis** — parse `.rs` files for cross-language duplicate detection
- [ ] **Language-agnostic tokenizer** — unified token pipeline across languages

### v5.3 — CI/CD Integration

- [ ] **GitHub Actions integration** — pre-built action for quality gates
- [ ] **Trend tracking** — compare reports across commits, show quality delta
- [ ] **PR comments** — automatically post findings on pull requests
- [ ] **Badge generation** — code health badges for README
- [ ] **Exit code support** — non-zero exit on critical findings

### v5.4 — Advanced AI Features

- [ ] **Auto-refactoring** — generate actual refactored code for flagged smells
- [ ] **Design pattern detection** — identify common patterns and anti-patterns
- [ ] **Security auto-fix** — suggest secure alternatives for Bandit findings
- [ ] **Multi-model support** — use different LLMs for different analysis tasks

### v6.0 — Platform

- [ ] **Web dashboard** — persistent web UI for browsing analysis results
- [ ] **Project history** — track code health over time with charts
- [ ] **Team features** — shared rules, team-specific thresholds
- [ ] **Plugin system** — custom smell detectors as plugins
- [ ] **IDE integration** — VS Code extension for inline smell highlighting

---

## Design Philosophy

1. **Zero dependencies first** — core features work with stdlib only
2. **Fast by default** — heuristics first, LLM only for enrichment
3. **Rust where it matters** — port CPU-hot-paths, not glue code
4. **Test everything** — maintain 500+ tests with parity verification
5. **Graceful degradation** — works on any terminal, any OS, with or without Rust
