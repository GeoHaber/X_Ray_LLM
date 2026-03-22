# X-Ray LLM — TODO

## Done ✅

### Scan Architecture (multi-session effort)
- [x] Replaced SSE streaming with async background thread + client polling
- [x] POST `/api/scan` starts daemon thread, returns immediately
- [x] GET `/api/scan-progress` returns live `{status, files_scanned, total_files, findings_count}`
- [x] GET `/api/scan-result` returns full payload when done
- [x] Cache-Control no-store headers on all JSON responses
- [x] Cache-buster `?_t=` on all client GET requests

### UI Fixes
- [x] Moved Scan/Stop buttons to top of sidebar (always visible, never destroyed)
- [x] Live pipeline status in sidebar: Starting → Scanning X/Y → Loading → Rendering → Complete ✔
- [x] Stop button appears only during active scan, hides on completion/error
- [x] Null-safe `_scanBtnSet()` helper prevents crash when mainContent is replaced
- [x] `_scanAborted` JS flag breaks polling and fetch loops on Stop
- [x] `showFatalError()` always shows errors visually instead of silent hangs
- [x] Last-resort `alert()` if even the error display crashes

### Large Scan Handling
- [x] `renderFindingsList()` capped at 500 findings with warning banner
- [x] `renderByFile()` already limited to 200 files
- [x] Programmatic scan of 76,049 files / 290,735 findings completes without crash

### Tests
- [x] 318+ tests passing (pytest)
- [x] Exhaustive monkey test suite (143 tests, 12 categories)
- [x] Programmatic scan verified for both small (249 files) and large (76k files) directories

### Documentation
- [x] X_RAY_LLM_GUIDE.md updated: sidebar layout, scan architecture, API endpoints
- [x] All pushed to GitHub (`master`)

---

## To Do 🔲

### P0 — Critical (must fix)

- [ ] **Browser retest after latest fixes** — server is running but user hasn't confirmed the full scan→results flow works end-to-end in browser yet (small scan first, then large)
- [ ] **Large scan rendering** — verify the 500-finding cap + warning banner actually displays correctly in browser with 290k findings

### P1 — High Priority

- [ ] **Multi-project scan support** — When scanning a deep directory containing many projects (e.g. `C:\Users\dvdze\Documents\_Python` with dozens of repos), detect project boundaries (look for `pyproject.toml`, `setup.py`, `requirements.txt`, `.git/`, `Cargo.toml`, `package.json`) and:
  - Group findings by project
  - Create a **project selector** in the sidebar or a dashboard view
  - Show per-project grade cards (A-F), finding counts, health scores
  - Allow drilling into any single project for detailed findings/fixes
  - Store per-project results separately for comparison over time

- [ ] **Pagination for findings** — Replace the hard 500 cap with proper pagination (Load More / virtual scroll) so users can browse all findings without DOM crash

- [ ] **Scan result persistence** — Save scan results to disk (JSON) so they survive server restart and can be loaded later without re-scanning

### P2 — Medium Priority

- [ ] **Before/After comparison** — After fixing issues and re-scanning, show a diff: what improved, what regressed, new vs resolved findings
- [ ] **Export results** — Download scan results as JSON, CSV, or HTML report
- [ ] **Severity filter in results** — Client-side filter to show/hide HIGH/MEDIUM/LOW findings after scan completes
- [ ] **Search within findings** — Text search across file paths, rule IDs, descriptions
- [ ] **Progress ETA** — Show estimated time remaining based on files/second rate during scan
- [ ] **Stop scan cleanup** — After stopping a scan, show partial results instead of blank screen

### P3 — Nice to Have

- [ ] **Scan history timeline** — Graph showing grade/score over time for the same project
- [ ] **Auto-refresh on file change** — Watch mode: re-scan changed files automatically
- [ ] **Keyboard shortcuts** — Ctrl+Enter to scan, Escape to stop, arrow keys for navigation
- [ ] **Dark/light theme persistence** — Remember theme choice in localStorage
- [ ] **Sidebar collapse** — Toggle sidebar to give more space to results on small screens
- [ ] **Rust scanner parity** — Bring Rust scanner up to 42 rules (currently 28)
- [ ] **WebSocket for progress** — Replace polling with WebSocket for instant updates (lower overhead than 400ms polls)

---

## Known Issues ⚠️

- `Stop-Process: Cannot stop process 'Idle (0)'` error appears when killing server — harmless but confusing
- Server sometimes holds port 8077 after Ctrl+C; may need `Stop-Process -Force` on the PID
- Scanning very large directories (76k+ files) takes ~130s server-side; no cancel-and-show-partial-results yet

---

*Last updated: March 16, 2026*
