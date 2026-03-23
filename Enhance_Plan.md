# X-Ray LLM — Enhancement Plan

**Date:** 2026-03-23
**Author:** GitHub Copilot (Tech Lead)

---

## Priority Legend
- **CRITICAL** — Must fix before any release
- **HIGH** — Should fix in next sprint
- **MEDIUM** — Plan for next milestone
- **LOW** — Backlog / nice-to-have

---

## Prioritized Action List

### 1. Fix Ruff Lint Violations (17 issues)
- **Priority:** HIGH
- **Description:** Clean 17 auto-fixable lint violations in test_comprehensive.py and test_e2e_real.py (unused imports, unsorted imports, unused variables, Yoda conditions)
- **Estimated Effort:** 5 minutes (auto-fix)
- **Dependencies:** None
- **Verification:** `python -m ruff check .` returns 0 violations
- **Command:** `python -m ruff check --fix --unsafe-fixes .`

### 2. Apply Ruff Formatting to All Files
- **Priority:** HIGH
- **Description:** 51 of 76 Python files have formatting drift. Apply consistent Black-compatible formatting.
- **Estimated Effort:** 2 minutes (auto-format)
- **Dependencies:** None
- **Verification:** `python -m ruff format --check .` returns "0 files would be reformatted"
- **Command:** `python -m ruff format .`

### 3. Sync Rust Scanner Rules (28 → 42)
- **Priority:** MEDIUM
- **Description:** The Rust scanner has 28 of 42 rules. Run the rule generation script to add the 14 newer rules (SEC-011–014, QUAL-011–013, PY-009–011, PORT-001–004).
- **Estimated Effort:** 30 minutes (generation + Rust build + validation)
- **Dependencies:** Rust toolchain installed
- **Verification:** `python build.py --validate` passes with 42 rules

### 4. Add OpenAPI/Swagger Specification
- **Priority:** MEDIUM
- **Description:** Generate a formal OpenAPI 3.0 spec for all 31+ REST endpoints. Currently documented in X_RAY_LLM_GUIDE.md but not machine-readable.
- **Estimated Effort:** 4 hours
- **Dependencies:** None
- **Verification:** OpenAPI spec validates against swagger-editor; all endpoints have request/response schemas

### 5. Address QUAL-003/QUAL-004 Fixer Line Shift
- **Priority:** MEDIUM
- **Description:** The int()/float() fixers wrap code in try/except, which shifts line numbers for subsequent findings in the same file. The bulk fixer processes bottom-up but rescan still flags shifted lines. Consider re-scanning after each fix application.
- **Estimated Effort:** 2 hours
- **Dependencies:** None
- **Verification:** test_fix_eliminates_finding[QUAL-003] and [QUAL-004] pass (currently skipped)

### 6. Add Rate Limiting / Auth to Web Server
- **Priority:** MEDIUM (when deploying beyond localhost)
- **Description:** ui_server.py has no authentication or rate limiting. For local use this is fine, but if exposed on a network, add basic auth or API key.
- **Estimated Effort:** 3 hours
- **Dependencies:** Decision on auth mechanism
- **Verification:** Unauthenticated requests rejected when auth is enabled

### 7. Improve False Positive Suppression for SEC-007 (eval)
- **Priority:** LOW
- **Description:** SEC-007 fires on eval() in comments and docstrings. 2 tests are currently skipped for this. Adding string/comment awareness for SEC-007 would eliminate these false positives.
- **Estimated Effort:** 1 hour
- **Dependencies:** None
- **Verification:** test_eval_in_comment_no_fire and test_eval_in_docstring_no_fire pass

### 8. Python 3.14 Compatibility Preparation
- **Priority:** LOW
- **Description:** ast.Str deprecation warning appears from external dependencies in Python 3.13. Monitor and update pip-audit/safety when they release compatible versions.
- **Estimated Effort:** 30 minutes (when upstream fix is available)
- **Dependencies:** Upstream library updates
- **Verification:** `python -m pytest tests/ -W error` passes with zero deprecation warnings

### 9. Add Parallel Scanning with ProcessPoolExecutor
- **Priority:** LOW
- **Description:** ProcessPoolExecutor is imported in scanner.py but not used for file-level parallelism. For very large codebases (10K+ files), parallel scanning could provide 3-5x speedup.
- **Estimated Effort:** 4 hours
- **Dependencies:** None
- **Verification:** Benchmark: scan of 10K-file project completes in < 30s

### 10. Add CHANGELOG.md Entries for Recent Work
- **Priority:** LOW
- **Description:** CHANGELOG.md should document the 14 new rules (SEC-011–014, QUAL-011–013, PY-009–011, PORT-001–004), AST validators, and PM Dashboard features added since v0.2.0.
- **Estimated Effort:** 30 minutes
- **Dependencies:** None
- **Verification:** CHANGELOG reflects all features in X_RAY_LLM_GUIDE.md

---

## Summary Table

| # | Action | Priority | Effort | Impact |
|---|--------|----------|--------|--------|
| 1 | Fix Ruff lint violations | HIGH | 5 min | Clean CI gate |
| 2 | Apply Ruff formatting | HIGH | 2 min | Consistent codebase |
| 3 | Sync Rust rules (28→42) | MEDIUM | 30 min | Full Rust parity |
| 4 | OpenAPI specification | MEDIUM | 4 hours | Machine-readable API docs |
| 5 | QUAL-003/004 fixer line shift | MEDIUM | 2 hours | 2 more tests pass |
| 6 | Auth for web server | MEDIUM | 3 hours | Network deployment safe |
| 7 | SEC-007 false positive fix | LOW | 1 hour | 2 more tests pass |
| 8 | Python 3.14 compat | LOW | 30 min | Future-proof |
| 9 | Parallel scanning | LOW | 4 hours | Performance at scale |
| 10 | CHANGELOG updates | LOW | 30 min | Documentation complete |

---

*Generated by GitHub Copilot*
