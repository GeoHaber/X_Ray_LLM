# X-Ray LLM — Enhancement Plan (Unified Roadmap)

**Date:** 2026-03-26  
**Status as of this date:** 42 rules, 45 endpoints, 1330+ tests (1141 passing + 12 skipped), 7 fixers, 5 AST validators, 9 PM Dashboard features

---

## Priority Legend
- **P0 — CRITICAL** — Must fix before any release
- **P1 — HIGH** — Should fix in next sprint
- **P2 — MEDIUM** — Plan for next milestone
- **P3 — LOW** — Backlog / nice-to-have

---

## P0 — Critical

### 1. Browser End-to-End Retest
- **Source:** TODO.md P0
- **Description:** Server is running but full scan→results flow needs confirmation in browser (small scan first, then large). Verify 500-finding cap + warning banner renders correctly with 290K findings.
- **Effort:** 30 minutes (manual testing)
- **Dependencies:** None
- **Verification:** Visual confirmation: scan completes, findings render, cap banner shows

### 2. Fix Ruff Lint Violations
- **Source:** Enhance_Plan v1 #1
- **Description:** Clean auto-fixable lint violations (unused imports, unsorted imports, unused variables, Yoda conditions).
- **Effort:** 5 minutes (auto-fix)
- **Dependencies:** None
- **Verification:** `python -m ruff check .` returns 0 violations
- **Command:** `python -m ruff check --fix --unsafe-fixes .`

### 3. Apply Ruff Formatting to All Files
- **Source:** Enhance_Plan v1 #2
- **Description:** Apply consistent Black-compatible formatting to all Python files.
- **Effort:** 2 minutes (auto-format)
- **Dependencies:** None
- **Verification:** `python -m ruff format --check .` returns "0 files would be reformatted"
- **Command:** `python -m ruff format .`

---

## P1 — High Priority

### 4. Multi-Project Scan Support
- **Source:** TODO.md P1
- **Description:** When scanning a deep directory containing many projects, detect project boundaries (pyproject.toml, setup.py, .git/, Cargo.toml, package.json) and group findings by project. Add project selector in sidebar, per-project grade cards (A-F), and per-project result storage.
- **Effort:** 8-12 hours
- **Dependencies:** None
- **Verification:** Scan a directory with 5+ projects; each gets separate grade and drill-down

### 5. Findings Pagination
- **Source:** TODO.md P1
- **Description:** Replace the hard 500-finding cap with proper pagination (Load More button or virtual scroll) so users can browse all findings without DOM crash.
- **Effort:** 4 hours
- **Dependencies:** None
- **Verification:** Scan with 1000+ findings; user can page through all of them

### 6. Scan Result Persistence
- **Source:** TODO.md P1
- **Description:** Save scan results to disk (JSON) so they survive server restart and can be loaded later without re-scanning.
- **Effort:** 3 hours
- **Dependencies:** None
- **Verification:** Scan, stop server, restart, load previous results from disk

### 7. Sync Rust Scanner Rules (28 → 42)
- **Source:** Enhance_Plan v1 #3
- **Description:** The Rust scanner has 28 of 42 rules. Run generate_rust_rules.py to add 14 newer rules (SEC-011–014, QUAL-011–013, PY-009–011, PORT-001–004). This is also listed as TODO.md P3 item.
- **Effort:** 30 minutes (generation + build + validation)
- **Dependencies:** Rust toolchain installed
- **Verification:** `python build.py --validate` passes with 42 rules

---

## P2 — Medium Priority

### 8. Before/After Comparison View
- **Source:** TODO.md P2
- **Description:** After fixing issues and re-scanning, show a diff: what improved, what regressed, new vs resolved findings.
- **Effort:** 6 hours
- **Dependencies:** Scan result persistence (#6)
- **Verification:** Fix some issues, re-scan, see improvement summary

### 9. Export Results (JSON, CSV, HTML)
- **Source:** TODO.md P2
- **Description:** Download scan results as JSON, CSV, or HTML report directly from the web UI.
- **Effort:** 3 hours
- **Dependencies:** None
- **Verification:** Each export format opens correctly in its native viewer

### 10. Severity/Search Filtering in UI
- **Source:** TODO.md P2
- **Description:** Client-side filter to show/hide HIGH/MEDIUM/LOW findings after scan completes, plus full-text search across file paths, rule IDs, and descriptions.
- **Effort:** 4 hours
- **Dependencies:** None
- **Verification:** Toggle severity buttons; search narrows results

### 11. Progress ETA During Scan
- **Source:** TODO.md P2
- **Description:** Show estimated time remaining based on files/second rate during ongoing scan.
- **Effort:** 2 hours
- **Dependencies:** None
- **Verification:** Progress bar shows "~X seconds remaining" during scan

### 12. Stop Scan → Show Partial Results
- **Source:** TODO.md P2
- **Description:** After stopping a scan mid-way, show the findings collected so far instead of a blank screen.
- **Effort:** 2 hours
- **Dependencies:** None
- **Verification:** Stop a long scan at 50%; findings found so far are displayed

### 13. OpenAPI/Swagger Specification
- **Source:** Enhance_Plan v1 #4
- **Description:** Generate a formal OpenAPI 3.0 spec for all 45 REST endpoints. Currently documented in X_RAY_LLM_GUIDE.md but not machine-readable.
- **Effort:** 4 hours
- **Dependencies:** None
- **Verification:** OpenAPI spec validates; all endpoints have request/response schemas

### 14. QUAL-003/QUAL-004 Fixer Line Shift
- **Source:** Enhance_Plan v1 #5
- **Description:** The int()/float() fixers wrap code in try/except, shifting line numbers for subsequent findings. Implement rescan-after-fix or line-offset tracking.
- **Effort:** 2 hours
- **Dependencies:** None
- **Verification:** test_fix_eliminates_finding[QUAL-003] and [QUAL-004] pass

### 15. Rate Limiting / Auth for Web Server
- **Source:** Enhance_Plan v1 #6
- **Description:** ui_server.py has no auth or rate limiting. Add optional API key or basic auth for when exposed beyond localhost.
- **Effort:** 3 hours
- **Dependencies:** Decision on auth mechanism
- **Verification:** Unauthenticated requests rejected when auth is enabled

### 16. LSP Integration for Real-Time IDE Scanning
- **Source:** Research (2026 SAST best practices)
- **Description:** Expose X-Ray findings via Language Server Protocol so IDEs (VS Code, PyCharm) show warnings inline as you type. Semgrep, Ruff, and Pylint all provide LSP modes in 2026 — X-Ray should too.
- **Effort:** 12-16 hours
- **Dependencies:** LSP library (pygls or lsprotocol)
- **Verification:** VS Code extension shows X-Ray warnings in Problems panel

### 17. Incremental Scanning (Changed Files Only)
- **Source:** Research + existing `--incremental` / `--since` flags
- **Description:** The CLI supports `--incremental` and `--since COMMIT` but the web UI always does full scans. Wire incremental mode into the web UI: detect changed files via git diff, scan only those, merge with cached results.
- **Effort:** 4 hours
- **Dependencies:** Scan result persistence (#6)
- **Verification:** After changing 2 files, web UI scans only those 2 + shows merged results

---

## P3 — Nice to Have

### 18. SEC-007 False Positive Suppression
- **Source:** Enhance_Plan v1 #7
- **Description:** SEC-007 fires on eval() in comments and docstrings. Add string/comment awareness for this rule.
- **Effort:** 1 hour
- **Verification:** test_eval_in_comment_no_fire and test_eval_in_docstring_no_fire pass

### 19. Python 3.14 Compatibility
- **Source:** Enhance_Plan v1 #8
- **Description:** ast.Str deprecation in 3.13+. Monitor upstream fixes for pip-audit/safety.
- **Effort:** 30 minutes (when upstream fix is available)
- **Verification:** `python -m pytest tests/ -W error` zero deprecation warnings

### 20. Parallel Scanning with ProcessPoolExecutor
- **Source:** Enhance_Plan v1 #9
- **Description:** ProcessPoolExecutor is imported but unused. For 10K+ file codebases, parallel scanning could provide 3-5x speedup.
- **Effort:** 4 hours
- **Verification:** 10K-file scan completes in <30s

### 21. CHANGELOG.md Updates
- **Source:** Enhance_Plan v1 #10
- **Description:** Document all features added since v0.2.0: 14 new rules, AST validators, PM Dashboard, portability category.
- **Effort:** 30 minutes
- **Verification:** CHANGELOG reflects all features in X_RAY_LLM_GUIDE.md

### 22. Scan History Timeline
- **Source:** TODO.md P3
- **Description:** Graph showing grade/score over time for the same project.
- **Effort:** 6 hours
- **Dependencies:** Scan result persistence (#6)
- **Verification:** Timeline chart renders with at least 3 historical data points

### 23. Auto-Refresh Watch Mode
- **Source:** TODO.md P3
- **Description:** File-watcher mode: re-scan changed files automatically on save.
- **Effort:** 4 hours
- **Dependencies:** Incremental scanning (#17)
- **Verification:** Save a file; findings update within 2 seconds

### 24. UI Polish (Keyboard Shortcuts, Theme, Sidebar)
- **Source:** TODO.md P3
- **Description:** Ctrl+Enter to scan, Escape to stop, arrow key navigation, persistent dark/light theme, collapsible sidebar.
- **Effort:** 4 hours
- **Verification:** All shortcuts work; theme survives page reload

### 25. WebSocket for Progress
- **Source:** TODO.md P3
- **Description:** Replace 400ms polling with WebSocket for instant scan progress updates and lower overhead.
- **Effort:** 4 hours
- **Dependencies:** None
- **Verification:** Progress updates arrive instantly without polling

### 26. Supply Chain Security (SCA + SBOM)
- **Source:** Research (2026 SAST best practices)
- **Description:** xray/sca.py wraps pip-audit. Extend with SBOM generation (CycloneDX format) and integrate into the web UI as a dedicated view. Supply chain attacks are the #1 rising concern in 2026.
- **Effort:** 8 hours
- **Dependencies:** cyclonedx-python-lib
- **Verification:** SBOM JSON validates against CycloneDX 1.5 schema; web UI shows dependency tree

### 27. Taint Analysis for SEC-004/SEC-005
- **Source:** Research (Semgrep-style dataflow)
- **Description:** SEC-004 (SQL injection) and SEC-005 (SSRF) currently use regex. Add lightweight taint tracking: trace user input (request.args, sys.argv, input()) through assignments to dangerous sinks (execute(), urlopen()). Reduces false positives dramatically.
- **Effort:** 16-20 hours
- **Dependencies:** None
- **Verification:** Taint-tracked scan has ≥50% fewer false positives on test corpus vs regex-only

### 28. Tree-Sitter Based Parsing
- **Source:** Research (2026 SAST best practices)
- **Description:** Replace regex + Python AST with tree-sitter for multi-language parsing. Tree-sitter provides concrete syntax trees for 100+ languages, enabling uniform analysis across Python/JS/HTML. GitHub Code Scanning and Semgrep both moved to tree-sitter in 2024-2025.
- **Effort:** 40+ hours (major refactor)
- **Dependencies:** py-tree-sitter, tree-sitter-python, tree-sitter-javascript
- **Verification:** All 42 rules reimplemented; test suite still passes; parsing is 5-10x faster

---

## Summary Table

| # | Action | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 1 | Browser E2E retest | P0 | 30 min | Confirm working product |
| 2 | Fix Ruff lint violations | P0 | 5 min | Clean CI gate |
| 3 | Apply Ruff formatting | P0 | 2 min | Consistent codebase |
| 4 | Multi-project scan support | P1 | 8-12 hrs | Key user workflow |
| 5 | Findings pagination | P1 | 4 hrs | Usability at scale |
| 6 | Scan result persistence | P1 | 3 hrs | Enables history/comparison |
| 7 | Sync Rust rules (28→42) | P1 | 30 min | Full Rust parity |
| 8 | Before/after comparison | P2 | 6 hrs | Fix verification workflow |
| 9 | Export results | P2 | 3 hrs | Reporting workflow |
| 10 | Severity/search filter | P2 | 4 hrs | Finding navigation |
| 11 | Progress ETA | P2 | 2 hrs | UX polish |
| 12 | Partial results on stop | P2 | 2 hrs | UX improvement |
| 13 | OpenAPI spec | P2 | 4 hrs | Machine-readable API |
| 14 | QUAL fixer line shift | P2 | 2 hrs | 2 more tests pass |
| 15 | Auth for web server | P2 | 3 hrs | Network deployment |
| 16 | LSP integration | P2 | 12-16 hrs | IDE-native scanning |
| 17 | Incremental web scan | P2 | 4 hrs | Fast re-scans |
| 18 | SEC-007 false positive | P3 | 1 hr | 2 more tests pass |
| 19 | Python 3.14 compat | P3 | 30 min | Future-proof |
| 20 | Parallel scanning | P3 | 4 hrs | Performance at scale |
| 21 | CHANGELOG updates | P3 | 30 min | Docs complete |
| 22 | Scan history timeline | P3 | 6 hrs | Trend visualization |
| 23 | Auto-refresh watch mode | P3 | 4 hrs | Developer workflow |
| 24 | UI polish | P3 | 4 hrs | UX quality |
| 25 | WebSocket progress | P3 | 4 hrs | Lower overhead |
| 26 | SCA + SBOM | P3 | 8 hrs | Supply chain security |
| 27 | Taint analysis | P3 | 16-20 hrs | Fewer false positives |
| 28 | Tree-sitter parsing | P3 | 40+ hrs | Multi-language foundation |

**Total estimated backlog:** ~140-170 hours across 28 items.

---

## Research Notes (2026 SAST Landscape)

### Semgrep 2026
- Pattern-based scanning (like X-Ray) + taint analysis + secrets detection
- Free tier: 20 rules; Pro: full registry (~4000 rules)
- X-Ray advantage: fully local, no SaaS dependency, LLM-powered test generation

### Ruff 2026
- Fastest Python linter/formatter (Rust-based, 10-100x faster than Flake8)
- X-Ray already integrates Ruff for format checking; complement rather than competitor
- Both tools should run in CI: Ruff for style, X-Ray for security/quality/portability

### Tree-Sitter
- Concrete syntax trees for 100+ languages; GitHub and Semgrep use it
- X-Ray's regex+AST hybrid works well for Python but limits JS/HTML analysis
- Migration is a major effort but would unlock true multi-language support

### GitHub Code Scanning / SARIF
- X-Ray already outputs SARIF 2.1.0 — compatible with GitHub Security tab
- GitHub Actions integration via action.yml is already in place
- Opportunity: publish as a GitHub Marketplace action

### Incremental Analysis
- Google's Tricorder and Meta's Infer both scan only changed files
- X-Ray CLI supports `--incremental` and `--since COMMIT`; web UI needs wiring

### Supply Chain Security
- 2026 trend: SCA + SBOM generation alongside SAST
- X-Ray has basic pip-audit integration; CycloneDX SBOM generation would be valuable
- NIST, EU CRA, and US Executive Order all mandate SBOMs in 2025-2026

---

## Recently Completed

### TurboQuant KV Cache Quantization (P1) — 2026-03-26
- **Description:** Added KV cache quantization support to `LLMConfig` and `LLMEngine` via `type_k`/`type_v` parameters (maps to llama-cpp-python's GGML type enums). Enables 2-4x VRAM reduction for KV cache with existing quantization types (q8_0, q4_0), and future 4.6x compression when TurboQuant (Google, ICLR 2026) lands in upstream llama.cpp.
- **New env vars:** `XRAY_TYPE_K`, `XRAY_TYPE_V` (accept names like `q8_0` or raw ints), `XRAY_FLASH_ATTN` (bool)
- **Files changed:** `xray/llm.py` (added `GGML_KV_TYPES` dict, `_resolve_kv_type()`, 3 new `LLMConfig` fields, kwargs passthrough in `_ensure_model()`), `tests/test_llm_mock.py` (22 new tests), `X_RAY_LLM_GUIDE.md` (config docs)
- **Impact:** Users with VRAM-constrained GPUs can now fit larger contexts (16K-32K) or run bigger models by setting `XRAY_TYPE_K=q8_0 XRAY_TYPE_V=q8_0 XRAY_FLASH_ATTN=true`

---

*Unified from Enhance_Plan.md (v1, 10 items) + TODO.md (P0-P3) + SAST landscape research. Generated by GitHub Copilot.*
