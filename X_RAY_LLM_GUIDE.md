# X-Ray LLM — Complete Feature Guide & Reference

> **Purpose**: This document is the single source of truth for everything X-Ray LLM can do.
> It is designed to be read by both humans and AI assistants so they can answer any question
> about the tool's capabilities, usage, and architecture.

---

## Table of Contents

1. [What Is X-Ray LLM?](#1-what-is-x-ray-llm)
2. [Quick Start](#2-quick-start)
3. [Architecture Overview](#3-architecture-overview)
4. [The 42 Scan Rules](#4-the-42-scan-rules)
5. [The Web UI](#5-the-web-ui)
6. [How To: Scan a Project](#6-how-to-scan-a-project)
7. [How To: Read & Filter Results](#7-how-to-read--filter-results)
8. [How To: Auto-Fix Issues](#8-how-to-auto-fix-issues)
9. [How To: Use the 19 Analysis Tools](#9-how-to-use-the-19-analysis-tools)
9a. [Dependency Freshness Checker](#9a-dependency-freshness-checker)
10. [How To: Use the PM Dashboard](#10-how-to-use-the-pm-dashboard)
11. [How To: Use the CLI & Agent Loop](#11-how-to-use-the-cli--agent-loop)
12. [How To: Build & Use the Rust Scanner](#12-how-to-build--use-the-rust-scanner)
13. [Grading System](#13-grading-system)
14. [All API Endpoints Reference](#14-all-api-endpoints-reference)
15. [All Analyzer Functions Reference](#15-all-analyzer-functions-reference)
16. [Configuration & Environment](#16-configuration--environment)
17. [Testing](#17-testing)
18. [File Map](#18-file-map)
19. [Troubleshooting & FAQ](#19-troubleshooting--faq)

---

## 1. What Is X-Ray LLM?

X-Ray LLM is a **self-improving code quality agent** that automates the full cycle:

```
SCAN → TEST → FIX → VERIFY → LOOP
```

It scans codebases for security vulnerabilities, quality issues, Python-specific bugs, and
portability problems using **42 pattern-based rules** sourced from real bugs found in real
projects — not synthetic patterns.

**Key capabilities:**
- **Dual scan engines** — Python (42 rules, cross-platform) + Rust (28 rules, optional, ~10× faster)
- **7 deterministic auto-fixers** — no LLM needed for common fixes
- **LLM-powered fixes** — uses local models (Qwen, DeepSeek, Codestral) via llama-cpp-python
- **Rich web UI** — 28+ views, interactive graphs, one-click tools
- **19+ analysis tools** — dead code, smells, duplicates, formatting, type checking, circular calls, coupling, unused imports, connections, and more
- **9 PM Dashboard features** — risk heatmaps, module grades, release confidence, sprint planning, architecture mapping, call graphs, circular call detection, coupling metrics, unused import analysis
- **Dependency freshness checker** — PyPI version checks with upgrade impact analysis
- **AST-based false positive reduction** — 3 AST validators suppress noise for PY-001, PY-005, PY-006
- **Export** — JSON, SARIF (GitHub Code Scanning compatible), and text output via REST API and CLI

---

## 2. Quick Start

### Start the Web UI (no LLM required)

```bash
python ui_server.py
```

Open **http://127.0.0.1:8077** in your browser. The web UI provides the full experience:
scan projects, view results, run analysis tools, auto-fix issues, and explore the PM Dashboard.

### Scan from the Command Line

```bash
# Dry-run scan — no changes, just report findings
python -m xray.agent /path/to/project --dry-run

# High-severity only
python -m xray.agent /path/to/project --severity HIGH --dry-run

# Scan + auto-fix with LLM (requires a GGUF model file)
export XRAY_MODEL_PATH=/path/to/model.gguf
python -m xray.agent /path/to/project --fix
```

### Install Dependencies

```bash
# Recommended: use Astral's uv for fast, reliable installs
python setup_tools.py          # First-time bootstrap (installs uv, ruff, ty)
python update_tools.py --check  # Verify versions

# Or install manually
pip install llama-cpp-python pytest ruff bandit
uv tool install ruff ty        # Astral toolchain (type checker + linter)
```

Only `pytest` is strictly required for scanning. The rest unlock additional analysis tools.
`ruff` enables the Format and Ruff Fix tools; `ty` (Astral's Rust-based type checker) enables Type Check.
`uv` is optional but recommended — it manages tool installs and provides faster dependency resolution.

---

## 3. Architecture Overview

```
  ┌───────────┐
  │   SCAN    │  28 rules (10 Security + 10 Quality + 8 Python)
  └─────┬─────┘  Python scanner (42 rules) + Rust scanner (28 rules)
        │
  ┌─────▼─────┐
  │   TEST    │  Auto-generate pytest tests for each finding
  └─────┬─────┘  via local LLM (Qwen2.5-Coder, DeepSeek, Codestral)
        │
  ┌─────▼─────┐
  │    FIX    │  7 deterministic fixers + LLM-generated patches
  └─────┬─────┘  Preview diffs before applying
        │
  ┌─────▼─────┐
  │  VERIFY   │  Run full test suite after each fix
  └─────┬─────┘  Confirm fixes don't break anything
        │
  ┌─────▼─────┐
  │   LOOP    │  Re-scan → still findings? → retry (max 3)
  └─────┬─────┘
        │
  ┌─────▼─────┐
  │  REPORT   │  JSON summary + human-readable output
  └───────────┘
```

### Component Map

| Component | File(s) | Role |
|-----------|---------|------|
| Scanner (Python) | `xray/scanner.py`, `xray/rules/*.py` | Pattern-based scanning engine (42 rules) with string/comment-aware filtering + AST validators |
| Scanner (Rust) | `scanner/src/` | Optional high-performance scanner (28 rules) |
| Agent Loop | `xray/agent.py` | Orchestrates SCAN→TEST→FIX→VERIFY→LOOP |
| LLM Interface | `xray/llm.py` | Local LLM inference via llama-cpp-python |
| Compat Checker | `xray/compat.py` | Python version, dependency version, API compatibility, and PyPI freshness verification |
| Test Runner | `xray/runner.py` | Executes pytest, parses results |
| Auto-Fixer | `xray/fixer.py` | 7 deterministic fixers + LLM fallback |
| Web Server | `ui_server.py` | HTTP API (31+ endpoints) on port 8077 |
| Web UI | `ui.html` | Single-page app with 28+ views |
| Analyzers | `analyzers/` | Package of 11 modules: 23+ analysis functions (smells, dead code, coupling, circular calls, PM Dashboard, etc.) |
| Build System | `build.py` | Rust cross-compilation + validation |
| Services | `services/` | Business logic: app state, scan manager, git analyzer, chat engine, SATD scanner |
| API Routes | `api/` | 5 route modules: scan, fix, analysis, PM dashboard, browse |
| Constants | `xray/constants.py` | Shared constants (SKIP_DIRS, file extensions, path normalizer) |
| Types | `xray/types.py` | TypedDict definitions for all API responses |

---

## 4. The 42 Scan Rules

Every rule was sourced from a real bug found in a real project.

> **Note:** The Python scanner implements all 42 rules. The Rust scanner currently has the
> original 28 rules (SEC-001–010, QUAL-001–010, PY-001–008). Run `python generate_rust_rules.py`
> to sync the 14 new rules to Rust.

### Security Rules (14) — Prefix: SEC

| ID | Name | Severity | What It Detects | Auto-Fix? |
|----|------|----------|-----------------|-----------|
| SEC-001 | XSS: Template literal in innerHTML | HIGH | `el.innerHTML = \`${user}\`` | No |
| SEC-002 | XSS: String concat to innerHTML | HIGH | `el.innerHTML = "x" + var` | No |
| SEC-003 | Command injection: shell=True | HIGH | `subprocess.run(..., shell=True)` | **Yes** → `shell=False` |
| SEC-004 | SQL injection: Query formatting | HIGH | `execute(f"SELECT {col}")` | No |
| SEC-005 | SSRF: URL from user input | MEDIUM | `requests.get(user_url)` | No |
| SEC-006 | CORS misconfiguration: wildcard | MEDIUM | `Access-Control-Allow-Origin: *` | No |
| SEC-007 | Code injection: eval/exec | HIGH | `eval(user_input)` | No |
| SEC-008 | Hardcoded secret | MEDIUM | `password = 'hunter2'` | No |
| SEC-009 | Unsafe deserialization | HIGH | `pickle.loads(data)`, `yaml.load(...)` | **Yes** → `yaml.safe_load()` |
| SEC-010 | Path traversal | MEDIUM | `os.path.join(dir, '../etc')` | No |
| SEC-011 | Timing attack: == on secrets | MEDIUM | `password == user_input` | No |
| SEC-012 | Debug mode enabled | HIGH | `DEBUG=True`, `app.debug=True` | No |
| SEC-013 | Weak hash: MD5/SHA1 | MEDIUM | `hashlib.md5()`, `hashlib.sha1()` | No |
| SEC-014 | TLS verification disabled | HIGH | `requests.get(url, verify=False)` | No |

### Quality Rules (13) — Prefix: QUAL

| ID | Name | Severity | What It Detects | Auto-Fix? |
|----|------|----------|-----------------|-----------|
| QUAL-001 | Bare except clause | MEDIUM | `except:` with no type | **Yes** → `except Exception:` |
| QUAL-002 | Silent exception swallowing | LOW | `except X: pass` | No |
| QUAL-003 | Unchecked int() on user input | MEDIUM | `int(request.args['val'])` | **Yes** → try/except wrapper |
| QUAL-004 | Unchecked float() on user input | MEDIUM | `float(environ['NUM'])` | **Yes** → try/except wrapper |
| QUAL-005 | .items() on possibly-None return | LOW | `func().items()` | No |
| QUAL-006 | Non-daemon threads | MEDIUM | `Thread(..., daemon=False)` | No |
| QUAL-007 | TODO/FIXME markers | LOW | `# TODO: fix this` | No |
| QUAL-008 | Long sleep (10+ seconds) | MEDIUM | `time.sleep(30)` | No |
| QUAL-009 | Explicit keep-alive in HTTP | HIGH | `send_header('Connection', 'keep-alive')` | No |
| QUAL-010 | localStorage without try/catch | MEDIUM | `localStorage.setItem(...)` | No |
| QUAL-011 | Broad Exception catching | MEDIUM | `except Exception:` (too broad) | No |
| QUAL-012 | String concat in loop | LOW | `s += "..."` in loop (O(n²)) | No |
| QUAL-013 | Line exceeds 200 chars | LOW | Lines >200 characters | No |

### Python Rules (11) — Prefix: PY

| ID | Name | Severity | What It Detects | Auto-Fix? |
|----|------|----------|-----------------|-----------|
| PY-001 | Return type mismatch | MEDIUM | `def f() -> None: return {}` | No |
| PY-002 | .items() on method returning None | HIGH | `obj.method().items()` | No |
| PY-003 | Wildcard imports | MEDIUM | `from module import *` | No |
| PY-004 | print() debug statement | LOW | `print(x)` in production code | No |
| PY-005 | JSON without error handling | HIGH | `json.loads(data)` unprotected | **Yes** → try/except JSONDecodeError |
| PY-006 | Global mutation | MEDIUM | `global x; x = 5` | No |
| PY-007 | os.environ[] crashes on missing | MEDIUM | `os.environ['API_KEY']` | **Yes** → `os.environ.get('KEY', '')` |
| PY-008 | open() without encoding | MEDIUM | `open('file.txt')` | No |
| PY-009 | Captured but ignored exception | MEDIUM | `except SomeError as e: pass` | No |
| PY-010 | sys.exit() in library code | MEDIUM | `sys.exit(1)` (kills process) | No |
| PY-011 | Long isinstance chain | LOW | `isinstance(x, (A,B,C,D,E,...))` | No |

### Portability Rules (4) — Prefix: PORT

| ID | Name | Severity | What It Detects | Auto-Fix? |
|----|------|----------|-----------------|-----------|
| PORT-001 | Hardcoded user path | HIGH | `C:\Users\<username>\...` in code | No |
| PORT-002 | Hardcoded C:\AI\ path | HIGH | `C:\AI\...` paths | No |
| PORT-003 | Hardcoded Windows path | MEDIUM | Absolute `X:\...` paths | No |
| PORT-004 | Windows-only import | MEDIUM | `import winreg` without guard | No |

### AST-Based False Positive Reduction

Three rules have AST validators (inline in `xray/scanner.py`) that suppress false positives
by inspecting the parsed AST tree after the initial regex match:

| Rule | AST Validator | What It Checks |
|------|--------------|----------------|
| PY-001 | `_ast_validate_py001` | Only flags if function actually returns non-None value |
| PY-005 | `_ast_validate_py005` | Suppresses if `json.loads()` is inside try/except |
| PY-006 | `_ast_validate_py006` | Suppresses `global` at module level (no-op) |

---

## 5. The Web UI

The web UI is a single-page application served at **http://127.0.0.1:8077**.

### Layout

```
┌─────────────────────────────────────────────────────┐
│  Header: X-Ray Scanner   [Python ●] [Rust ● or ○]  │
├──────────┬──────────────────────────────────────────┤
│ Sidebar  │  Main Content Area                       │
│          │                                          │
│ Scan     │  ┌─ Tab Bar ─────────────────────────┐   │
│ Controls │  │ Findings │ Fixes │ Grade │ Risk  …│   │
│ [▶ Scan] │  └──────────────────────────────────┘   │
│ [■ Stop] │                                          │
│ Status:… │  (Active view content)                   │
│          │                                          │
│ [Browse] │                                          │
│          │                                          │
│ Settings │                                          │
│          │                                          │
│ Tools    │                                          │
│ ┌──┬──┐  │                                          │
│ │  │  │  │                                          │
│ └──┴──┘  │                                          │
│          │                                          │
│ PM Dash  │                                          │
│ ┌──┬──┐  │                                          │
│ │  │  │  │                                          │
│ └──┴──┘  │                                          │
├──────────┴──────────────────────────────────────────┤
│  Footer: Status bar                                 │
└─────────────────────────────────────────────────────┘
```

### Sidebar Sections

1. **Scan Controls** — Always at the top: Scan / Stop buttons, selected path, live pipeline status ("Starting scan...", "Scanning 50/249 files...", "Loading results...", "Scan complete ✔")
2. **Directory Browser** — Navigate folders, select project to scan
3. **Settings** — Engine (Python/Rust), severity filter, exclude patterns
4. **Quality Gate** — Configurable thresholds (max high, max medium, min score, max debt)
5. **Analysis Tools** — 16 buttons (2-column grid), each runs one analysis
6. **PM Dashboard** — 10 buttons (2-column grid), each runs a PM-level analysis
7. **Recent Scans** — Previously scanned directories for quick re-scan

### Scan Architecture

The scan uses an **async background thread + client polling** pattern:

1. **POST `/api/scan`** starts a background daemon thread and returns `{"status":"started","total_files":N}` immediately
2. **Client polls `GET /api/scan-progress`** every 400ms — returns `{"status":"scanning","files_scanned":X,"total_files":Y,"findings_count":Z,...}`
3. When status becomes `"done"`, client fetches **`GET /api/scan-result`** for the full result payload
4. Large result sets (290k+ findings) are capped at **500 rendered findings** in the DOM with a warning banner to prevent browser crashes
5. All JSON responses include `Cache-Control: no-store` headers; GET requests append cache-buster query parameters

### View Tabs (28+)

After running a scan or analysis, results appear in tabbed views:

| Tab | Source | Content |
|-----|--------|---------|
| Findings | Scan | Table of all findings, filterable by severity |
| Fixes | Scan | Grouped by rule, with preview diffs |
| Grade | Scan | Overall A-F grade card with score percentage |
| Risk | Scan | Heatmap of findings per file |
| SATD | Scan Debt tool | Technical debt markers (TODO, FIXME, HACK, etc.) |
| Hotspots | Git Hotspots tool | Most-changed files ranked by churn |
| Deps | Dep Graph tool | vis.js force-directed import dependency graph |
| Duplicates | Duplicates tool | Identical code block groups |
| Smells | Smells tool | Code smells by type (complexity, nesting, etc.) |
| Dead Code | Dead Code tool | Uncalled functions (>5 lines) |
| Types | Types tool | pyright type checking output |
| Health | Health tool | Project health checks (README, LICENSE, tests, CI, etc.) |
| Format | Format tool | Files that need ruff formatting |
| Bandit | Bandit tool | Security findings + hardcoded secrets |
| Release | Release tool | Release readiness checklist |
| AI | AI Detect tool | Suspected AI-generated code markers |
| Web | Web Smells tool | JS/HTML/CSS anti-patterns |
| Coupling | Coupling tool | Files that change together in git |
| Test Gen | Test Gen tool | Auto-generated pytest stubs |
| Remediation | (computed) | Estimated fix time per finding |
| PM: Risk | Risk Map | Color-coded treemap of per-file composite risk |
| PM: Modules | Module Cards | Per-directory A-F grade cards |
| PM: Confidence | Confidence | Large confidence percentage with checks |
| PM: Batches | Sprint Batches | 4 collapsible work-package cards |
| PM: Arch | Arch Map | vis.js architecture graph + warnings |
| PM: Calls | Call Graph | Hierarchical vis.js call graph |
| PM: Circular | Circular Calls | Function-level cycle detection, hub functions |
| PM: Coupling | Coupling | Module afferent/efferent coupling, instability, health |
| PM: Imports | Unused Imports | AST-based dead import detection |

---

## 6. How To: Scan a Project

### Via Web UI

1. Open **http://127.0.0.1:8077**
2. In the sidebar, **click folder icons** to browse to your project directory
3. Click **"Scan Project"** (or the green Scan button)
4. Choose engine: **Python** (default) or **Rust** (faster, if built)
5. Wait for the progress bar to complete
6. Results appear in the **Findings**, **Fixes**, and **Grade** tabs

### Via CLI

```bash
# Basic scan — prints findings to console
python -m xray.agent /path/to/project --dry-run

# Scan specific severity
python -m xray.agent /path/to/project --severity HIGH --dry-run

# Scan with excludes
python -m xray.agent /path/to/project --dry-run --exclude vendor/ node_modules/
```

### Via Rust Scanner

```bash
./xray-scanner /path/to/project --json
./xray-scanner . --severity HIGH
./xray-scanner . --exclude "vendor/" "test/"
```

### What Happens During a Scan

1. The scanner traverses the directory (skipping `__pycache__`, `.git`, `node_modules`, `venv`)
2. For each file, it detects the language (`.py` → Python, `.js/.ts` → JavaScript, `.html` → HTML)
3. Each line is tested against all applicable rules' regex patterns (Python scanner: 42 rules; Rust scanner: 28 rules)
4. Matches are collected as **findings** with: rule ID, severity, file, line, description, fix hint
5. Results are returned with a summary (total, high, medium, low counts)

---

## 7. How To: Read & Filter Results

### Findings Tab

After scanning, the **Findings** tab shows a table with columns:
- **Severity** — color-coded badge (HIGH = red, MEDIUM = yellow, LOW = blue)
- **Rule** — rule ID like SEC-003 or PY-005
- **File** — source file path (click to see in context)
- **Line** — line number where the issue was found
- **Description** — human-readable explanation of the problem

**Filtering**: Click severity badges in the summary bar to toggle HIGH/MEDIUM/LOW visibility.

### Grade Tab

Shows the overall project grade:
- **Letter grade** (A through F) in large text
- **Numeric score** (0-100)
- **Breakdown** by severity count
- Color-coded (green A → red F)

### Fixes Tab

Shows findings grouped by rule, with:
- **Rule description** and fix hint
- **Fixable badge** if the rule has a deterministic auto-fixer
- **Diff preview** showing what the fix would change
- **Apply** button (for fixable rules)

---

## 8. How To: Auto-Fix Issues

### Deterministic Fixers (7 Rules — No LLM Required)

These rules have built-in fixers that produce correct, safe transformations:

| Rule | What It Fixes |
|------|---------------|
| SEC-003 | `shell=True` → `shell=False` in subprocess calls |
| SEC-009 | `yaml.load()` → `yaml.safe_load()` |
| QUAL-001 | `except:` → `except Exception:` |
| QUAL-003 | `int(user_input)` → wrapped in `try/except (ValueError, TypeError)` |
| QUAL-004 | `float(user_input)` → wrapped in `try/except (ValueError, TypeError)` |
| PY-005 | `json.loads(data)` → wrapped in `try/except json.JSONDecodeError` |
| PY-007 | `os.environ['KEY']` → `os.environ.get('KEY', '')` |

### How to Apply Fixes via Web UI

1. Run a **Scan** first
2. Switch to the **Fixes** tab
3. For each fixable finding, you'll see a **diff preview** showing the before/after
4. Click **"Apply Fix"** to write the change to disk
5. Or click **"Apply All"** to batch-apply all fixable findings

### How to Apply Fixes via CLI

```bash
# The agent loop automatically applies fixes when --fix is used
export XRAY_MODEL_PATH=/path/to/model.gguf
python -m xray.agent /path/to/project --fix --max-retries 3
```

The agent will:
1. Scan for findings
2. Apply deterministic fixes (7 rules)
3. For remaining findings, ask the LLM to generate a fix
4. Run the test suite to verify
5. If tests fail, retry the fix (up to 3 times)
6. Re-scan and repeat until clean or retries exhausted

### Preview Without Applying

Via API: `POST /api/preview-fix` with `{rule_id, file, line}` — returns a diff without writing.

---

## 9. How To: Use the 19 Analysis Tools

All analysis tools are accessible from the **sidebar tool grid** in the Web UI. Each tool
works on the currently selected directory. Most tools work independently — you don't need
to run a scan first (though some tools produce richer results if scan data is available).

### Tool 1: Ruff Fix

**Button**: ☑️ Ruff Fix  
**What it does**: Runs `ruff check --fix` to auto-fix lint violations (unused imports, formatting, etc.)  
**Output**: List of files modified and violations fixed  
**Prerequisite**: `pip install ruff`

### Tool 2: Scan Debt (SATD)

**Button**: 📋 Scan Debt  
**What it does**: Scans for Self-Admitted Technical Debt markers (TODO, FIXME, HACK, XXX, SECURITY, etc.)  
**Output**: Lists every debt marker with file, line, category if available, and estimated effort  
**Categories**: defect, design, debt, test, documentation, requirement  
**Key metric**: Total estimated hours of debt

### Tool 3: Git Hotspots

**Button**: 🔥 Git Hotspots  
**What it does**: Analyzes `git log` to find the most frequently changed files (last 90 days)  
**Output**: Files ranked by churn count (number of commits touching them)  
**Use case**: High-churn files are often the most bug-prone — prioritize reviews there
**Prerequisite**: Must be a git repository

### Tool 4: Dependency Graph

**Button**: 🔗 Dep Graph  
**What it does**: Parses Python import statements to build a module dependency graph  
**Output**: Interactive vis.js force-directed graph (nodes = modules, edges = imports)  
**Interaction**: Drag nodes, zoom, hover for details  
**Use case**: Understand module coupling and identify tightly-coupled components

### Tool 5: Format Check

**Button**: 📄 Format  
**What it does**: Runs `ruff format --check` to find files that don't match standard formatting  
**Output**: List of files needing formatting, with a "Format All" option  
**Prerequisite**: `pip install ruff`

### Tool 6: Project Health

**Button**: 🏥 Health  
**What it does**: Checks 10 health indicators for the project  
**Output**: Score (0-100%) + pass/fail for each check  
**Checks**:
- README.md exists
- LICENSE file exists
- tests/ directory exists
- CI config exists (.github/workflows or similar)
- CHANGELOG.md exists
- .gitignore exists
- requirements.txt or pyproject.toml exists
- setup.py or setup.cfg exists
- No .env files committed
- Source-to-test ratio

### Tool 7: Bandit Security

**Button**: 🛡️ Bandit  
**What it does**: Runs Bandit (Python security linter) + AST-based secrets detection (API keys, tokens, passwords)  
**Output**: Security issues from Bandit + discovered hardcoded secrets  
**Prerequisite**: `pip install bandit`

### Tool 8: Dead Code

**Button**: 💀 Dead Code  
**What it does**: Finds functions defined but never called anywhere in the codebase  
**Output**: List of dead functions (>5 lines) with file, line, and function length  
**Exclusions**: `main`, `setup`, `teardown`, test functions, dunder methods are excluded  
**Use case**: Remove dead code to reduce maintenance burden

### Tool 9: Code Smells

**Button**: 👃 Smells  
**What it does**: Detects code smells using heuristics  
**Smell types detected**:
- **Long functions** (>50 lines)
- **High cyclomatic complexity** (>10 branches)
- **Deep nesting** (>4 levels)
- **Mutable default arguments** (`def f(x=[])`)
- **God classes** (>300 lines or >20 methods)
- **Bare except** clauses
- **Magic numbers** (unnamed numeric constants)

### Tool 10: Duplicates

**Button**: 📋 Duplicates  
**What it does**: Finds duplicate code blocks (exact match, 6-line minimum chunks)  
**Output**: Groups of identical code blocks with file locations  
**Algorithm**: Hash-based (MD5 of normalized lines)  
**Use case**: Refactor duplicated logic into shared functions

### Tool 11: Temporal Coupling

**Button**: 📅 Coupling  
**What it does**: Analyzes git history to find files that always change together  
**Threshold**: Files that co-change in ≥3 commits  
**Output**: Pairs of files with co-change count and percentage  
**Use case**: Files that always change together may need to be merged or refactored  
**Prerequisite**: Must be a git repository

### Tool 12: Type Check

**Button**: 🔎 Types  
**What it does**: Runs **ty** (Astral's Rust-based type checker, successor to pyright)  
**Output**: Diagnostics with severity, rule code, file/line/column  
**Prerequisite**: `uv tool install ty` (or `pip install ty`)

### Tool 13: Release Readiness

**Button**: 🚀 Release  
**What it does**: Evaluates if the project is ready for release  
**Checks**:
- Version defined somewhere
- CHANGELOG.md is up to date
- No critical TODO/FIXME markers
- Tests exist and structure is sound
- README.md has meaningful content
- No debug `print()` statements in source
- `.env.example` exists if `.env` is used
**Output**: Score (0-100%) + pass/fail per check + a boolean `ready`

### Tool 14: AI Code Detection

**Button**: 🤖 AI Detect  
**What it does**: Heuristically detects patterns common in AI-generated code  
**Patterns**: "Generated by", placeholder TODOs, formulaic docstrings, boilerplate comments  
**Output**: List of indicators with file, line, and type  
**Note**: Heuristic — false positives possible; meant for awareness, not enforcement

### Tool 15: Web Smells

**Button**: 🌐 Web Smells  
**What it does**: Detects anti-patterns in JavaScript, HTML, and CSS  
**Patterns**:
- `document.write()`
- `eval()` / `new Function()`
- `innerHTML` assignments
- Loose equality (`==` / `!=`)
- Nested `.then()` chains
- `console.log()` in production
- `var` instead of `let`/`const`
- `!important` in CSS
**Output**: Categorized smells with severity

### Tool 16: Test Generation

**Button**: 🧪 Test Gen  
**What it does**: Auto-generates pytest stub files for untested functions  
**Output**: Coverage percentage, list of tested/untested functions, generated stub code  
**Action**: Click "Copy All Stubs" to copy generated test code to clipboard  
**Use case**: Jump-start test writing by getting skeleton tests for every function

---

## 10. How To: Use the PM Dashboard

The PM Dashboard provides **project-manager-level insights** — the kind of analysis a wise,
experienced release manager would do before making ship/no-ship decisions.

All 9 PM Dashboard tools are in the sidebar under **"PM Dashboard"**.

### PM Tool 1: Risk Heatmap 🎯

**Button**: Risk Map  
**What it does**: Computes a composite risk score for every file in the project  
**How risk is calculated**:
```
risk_score = security_findings × 5
           + quality_findings × 2
           + code_smells × 2
           + git_churn × 3
           + duplicate_blocks × 1
```
**Output**:
- **Treemap visualization** — rectangles sized by lines of code, colored by risk (green → yellow → red)
- **Summary cards** — count of high-risk, medium-risk, and low-risk files
- **Top risk files list** — sorted by composite risk score with breakdown  

**Use case**: "Which files need the most attention? Where should we focus reviews?"

### PM Tool 2: Module Report Cards 📊

**Button**: Modules  
**What it does**: Grades every directory (module) in the project from A to F  
**How grades are computed**:
- Aggregate findings by directory
- Weighted formula: `HIGH×5 + MEDIUM×2 + LOW×0.5` per file count
- A (≤5), B (≤15), C (≤40), D (≤80), F (>80)  

**Output**:
- **Grid of module cards** — each shows:
  - Grade letter (large, color-coded)
  - Score out of 100
  - Module directory name
  - File count and LOC
  - HIGH/MEDIUM/LOW finding counts
  - Code smell count
  - Untested function count
- Sorted worst-first (F → A)  

**Use case**: "How is each team's module performing? Which modules drag down quality?"

### PM Tool 3: Release Confidence Meter 🎯

**Button**: Confidence  
**What it does**: Synthesizes all analysis into a single **release confidence percentage** (0-100%)  
**The 10 weighted checks**:

| Check | Points | What It Measures |
|-------|--------|-----------------|
| No critical security findings | 20 | Zero HIGH-severity SEC-* rules triggered |
| Test coverage ≥ 50% | 15 | Functions with corresponding test functions |
| No HIGH-severity findings at all | 10 | Zero HIGH findings of any category |
| No HIGH code smells | 10 | No long functions, high complexity, etc. |
| No circular dependencies | 10 | Architecture is acyclic |
| Release readiness ≥ 70% | 10 | Pre-release checklist passes |
| Project health ≥ 70% | 10 | README, tests, LICENSE, CI all present |
| No god modules | 5 | No module with ≥5 dependents |
| Dead code < 5 | 5 | Few uncalled functions |
| Code formatting passes | 5 | ruff format finds no issues |

**Total possible: 100 points**

**Output**:
- **Large confidence number** (72px font) with color — green (80%+), yellow (60-80%), orange (40-60%), red (<40%)
- **Progress bar** matching the confidence level
- **Narrative recommendation** — "Ready to ship", "Address top risks first", or "Significant work needed"
- **Top risks** — the most impactful failed checks, sorted by weight
- **All 10 checks** with ✅/❌, description, and weight  

**Use case**: "Are we ready to release? What's blocking us?"

### PM Tool 4: Sprint Action Batches 📋

**Button**: Batches  
**What it does**: Groups all findings and smells into time-bucketed work packages sorted by ROI  
**How ROI is calculated**:
```
impact = {HIGH: 10, MEDIUM: 4, LOW: 1}
effort_minutes = {SEC: 15, QUAL: 5, PY: 10, smell: 15}
ROI = impact / effort
```
**The 4 batches**:
1. **Quick Wins (< 4h)** — highest ROI items that can be fixed fast
2. **Sprint 1 (4-8h)** — next-priority items for a focused sprint
3. **Sprint 2 (8-16h)** — medium-effort improvements
4. **Backlog (16h+)** — lower-priority or high-effort items

**Output**:
- **4 collapsible batch cards** — each shows:
  - Batch name and color indicator
  - Number of items and total hours
  - Cumulative "% resolved after this batch" metric
  - Expandable item list with severity, rule ID, description, file, estimated minutes, ROI score
- Quick Wins batch is expanded by default; others collapsed  

**Tip**: Run **Scan** + **Smells** first for full data. Without scan data, only smell items appear.  

**Use case**: "What should we tackle this sprint? What gives us the biggest bang for the buck?"

### PM Tool 5: Architecture Map 🏗️

**Button**: Arch Map  
**What it does**: Visualizes the project's module architecture as an interactive graph  
**Analysis includes**:
- **Layer detection** — classifies each module as:
  - 🟢 **App** — application logic
  - 🔵 **Lib** — library/utility modules
  - 🟡 **Test** — test files
  - ⚪ **External** — third-party imports
- **Circular dependency detection** — finds import cycles using DFS
- **God module detection** — modules with ≥5 local dependents

**Output**:
- **Interactive vis.js graph** — nodes colored by layer, sized by importance
  - God modules shown larger with thick borders
  - Circular dependency edges shown in red dashed lines
  - Hover for details (module name, layer, LOC, import count)
- **Warning banners** for circular deps (red) and god modules (yellow)
- **Layer summary** — count of modules per layer  

**Use case**: "What does our architecture look like? Are there concerning structural patterns?"

### PM Tool 6: Call Graph 📞

**Button**: Call Graph  
**What it does**: Builds an AST-based function call graph showing who-calls-whom  
**Analysis includes**:
- **Entry point detection** — functions decorated with `@route`, `@get`, `@post`, `@command`, `@task`, `@cli`, or named `main`
- **Leaf detection** — functions that don't call any other local functions
- **Call resolution** — maps function calls to their definitions  

**Output**:
- **Interactive vis.js hierarchical graph** (top-down layout)
  - 🟢 Triangle = entry point
  - 🔵 Circle = regular function
  - ⚪ Circle = leaf function (no outgoing calls)
  - Size proportional to caller count
  - Hover for function name, file, line, line count
- **Entry points table** (up to 20) — the "doors into" the codebase
- **Leaf functions table** (up to 20) — the "bottom" of the call chain  

**Use case**: "What are the main entry points? What's the call flow? Where are the dead ends?"

### PM Tool 7: Circular Call Detection 🌀

**Button**: Circular  
**What it does**: Detects function-level circular call chains (macaroni code) using DFS cycle detection on the call graph  
**Analysis includes**:
- **Circular call chains** — functions that call each other in cycles (A→B→C→A)
- **Recursive functions** — functions that call themselves directly
- **Hub functions** — functions with high fan-in × fan-out scores (coordination smell)

**Output**:
- **Summary cards** — total functions, call edges, cycles, recursive, hubs
- **Circular chain list** — each cycle with arrow visualization and affected files
- **Hub functions table** — name, file, line, fan-in, fan-out, hub score
- **Recursive functions table** — function name, file, line

**Use case**: "Is our code tangled? Are there functions that endlessly call each other? Where are the spaghetti junctions?"

### PM Tool 8: Module Coupling & Cohesion 🔗

**Button**: Coupling  
**What it does**: Computes per-module coupling metrics and health classification  
**Metrics per module**:
- **Afferent coupling (Ca)** — how many other modules depend on this one
- **Efferent coupling (Ce)** — how many modules this one depends on
- **Instability (I)** — Ce/(Ca+Ce), 0 = stable, 1 = unstable
- **Cohesion estimate** — function count / LOC ratio
- **Health** — classified as: healthy, god_module, fragile, isolated, or dependent

**Output**:
- **Summary cards** — total modules, average instability, breakdown by health category
- **God module alerts** (red) — modules with too many inbound AND outbound dependencies
- **Fragile module alerts** (yellow) — unstable modules that others depend on
- **Full module table** — LOC, functions, Ca, Ce, instability, cohesion, health status (color-coded)

**Use case**: "Which modules are tangled? What would break if I changed this module? Is our architecture healthy?"

### PM Tool 9: Unused Imports 🧹

**Button**: Imports  
**What it does**: AST-based detection of imported names that are never referenced in the file  
**Analysis includes**:
- **Import collection** — all `import` and `from ... import` names and aliases
- **Reference scanning** — all Name nodes in AST + string annotations (for type hints)
- **Comparison** — imported names not found in any reference are flagged

**Output**:
- **Summary cards** — total unused imports, files affected
- **By-file chips** — file name with count of unused imports per file
- **Detail table** — file, line number, import name (capped at 100 rows)

**Use case**: "Are we importing things we don't use? Clean up dead imports to reduce clutter."

---

## 11. How To: Use the CLI & Agent Loop

### Basic Scanning

```bash
# Dry-run: scan and display findings, no changes
python -m xray.agent /path/to/project --dry-run

# Severity filter
python -m xray.agent /path/to/project --severity HIGH --dry-run

# Exclude paths
python -m xray.agent /path/to/project --dry-run --exclude vendor/ node_modules/

# Git-diff scan — only check files changed since a reference
python -m xray.agent /path/to/project --dry-run --since HEAD~5
python -m xray.agent /path/to/project --dry-run --since main

# Incremental scan — skip unchanged files since last scan
python -m xray.agent /path/to/project --dry-run --incremental

# Baseline — only show NEW findings vs previous scan
python -m xray.agent /path/to/project --dry-run --baseline previous_scan.json

# Output formats
python -m xray.agent /path/to/project --format json -o results.json
python -m xray.agent /path/to/project --format sarif -o results.sarif
```

### Auto-Fix Loop (Requires LLM Model)

```bash
# Set up the LLM model
export XRAY_MODEL_PATH=/path/to/qwen2.5-coder-32b-q4_k_m.gguf

# Run full SCAN → TEST → FIX → VERIFY → LOOP cycle
python -m xray.agent /path/to/project --fix

# Limit retry attempts
python -m xray.agent /path/to/project --fix --max-retries 3
```

### What the Agent Loop Does

1. **SCAN** — runs all 42 rules against the codebase (Python engine) or 28 rules (Rust engine)
2. **TEST** — generates pytest tests for each finding (via LLM)
3. **FIX** — applies deterministic fixers first, then LLM-generated patches
4. **VERIFY** — runs `pytest` to confirm no regressions
5. **LOOP** — re-scans; if findings remain, retries (up to max-retries)
6. **REPORT** — outputs JSON summary with all findings, fixes applied, and test results

### Rust Scanner CLI

```bash
# Build first (one-time)
cd scanner && cargo build --release && cd ..

# Fast scan with JSON output
./scanner/target/release/xray-scanner /path/to/project --json

# Filter and exclude
./xray-scanner . --severity HIGH --exclude "vendor/" "test/"
```

---

## 12. How To: Build & Use the Rust Scanner

The Rust scanner is an optional, high-performance alternative to the Python scanner.
It currently implements the original 28 rules with identical regex patterns, running ~10× faster.

> **Syncing new rules:** The Python scanner has 42 rules (14 new rules added: timing
> attacks, debug mode, weak hashing, TLS bypass, broad Exception catching,
> string concat in loops, long lines, captured-ignored exceptions, sys.exit in library
> code, long isinstance chains, and 4 portability rules for hardcoded paths/imports).
> Run `python generate_rust_rules.py` to sync them.

### Prerequisites

- Rust toolchain (rustup, cargo)
- Python 3.10+ (for build.py and rule generation)

### Build

```bash
# Full build: generate rules → cargo test → release build
python build.py

# Just run cargo tests
python build.py --test-only

# Cross-validate Rust output against Python scanner
python build.py --validate

# Show detected OS/arch/target triple
python build.py --info
```

### Cross-Compilation

```bash
# Build for Linux from any platform
python build.py --target linux

# Build for macOS
python build.py --target macos
```

### Supported Platforms

| OS | Architectures |
|----|---------------|
| Windows | x86_64, ARM64 |
| Linux | x86_64, ARM64, ARMv7 |
| macOS | x86_64 (Intel), ARM64 (Apple Silicon) |

### Using the Rust Scanner

Once built, the binary is at `scanner/target/release/xray-scanner` (or `.exe` on Windows).

The web UI auto-detects the Rust binary and enables the **Rust engine option** in the scan
controls. You can also use it directly from the command line:

```bash
./xray-scanner /path/to/project --json
```

---

## 13. Grading System

### Per-Module Grades (A-F)

Grades are computed per directory using a weighted finding formula:

```
weighted = HIGH × 5 + MEDIUM × 2 + LOW × 0.5
score = max(0, 100 - (weighted / file_count) * 10)
```

| Grade | Score Range | Meaning |
|-------|-------------|---------|
| A | 90-100 | Excellent — minimal issues |
| B | 75-89 | Good — some minor issues |
| C | 60-74 | Acceptable — needs improvement |
| D | 30-59 | Poor — significant problems |
| F | 0-29 | Failing — critical issues |

### Overall Project Grade

The overall grade uses the same formula applied across all files in the scanned directory.

### Confidence Score (0-100%)

The PM Dashboard confidence meter uses a different, more comprehensive system based on
10 weighted checks that assess security, testing, architecture, and code quality.
See the [PM Tool 3: Release Confidence Meter](#pm-tool-3-release-confidence-meter-) section.

---

## 14. All API Endpoints Reference

The server listens on **port 8077** (configurable via `--port`) and exposes these REST endpoints:

### Static & Info

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve the web UI (ui.html) |
| GET | `/api/info` | Platform, Python version, Rust status, rules count (42), fixable rules |
| GET | `/api/env-check` | Check tool availability (ruff, bandit, ty, git, etc.) |
| GET | `/api/dependency-check` | PyPI freshness check for all dependencies |

### File Browsing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/browse?path=...` | List directory contents (folders first, sorted, respects XRAY_BROWSE_ROOTS) |

### Scanning

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/scan` | `{directory, engine, severity, excludes[]}` | Start async background scan, returns `{status, total_files}` |
| GET | `/api/scan-progress` | | Poll scan progress `{status, files_scanned, total_files, findings_count}` |
| GET | `/api/scan-result` | | Fetch completed scan result (full findings payload) |
| POST | `/api/abort` | `{}` | Cancel running scan |

### Auto-Fix

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/preview-fix` | `{rule_id, file, line}` | Preview fix diff (no write) |
| POST | `/api/apply-fix` | `{rule_id, file, line}` | Apply single fix to disk |
| POST | `/api/apply-fixes-bulk` | `{fixes[]}` | Batch-apply multiple fixes |

### Analysis Tools

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/satd` | `{directory}` | SATD technical debt markers |
| POST | `/api/git-hotspots` | `{directory}` | Git churn analysis (90 days) |
| POST | `/api/imports` | `{directory}` | Import dependency graph |
| POST | `/api/ruff` | `{directory}` | Run ruff check --fix |
| POST | `/api/format` | `{directory}` | Run ruff format --check |
| POST | `/api/health` | `{directory}` | 10-point project health score |
| POST | `/api/bandit` | `{directory}` | Bandit security + secrets detection |
| POST | `/api/dead-code` | `{directory}` | Find uncalled functions |
| POST | `/api/smells` | `{directory}` | Detect code smells |
| POST | `/api/duplicates` | `{directory}` | Find duplicate code blocks |
| POST | `/api/temporal-coupling` | `{directory}` | Git file co-change analysis |
| POST | `/api/typecheck` | `{directory}` | Run ty type checker |
| POST | `/api/release-readiness` | `{directory}` | Release readiness check |
| POST | `/api/ai-detect` | `{directory}` | AI-generated code detection |
| POST | `/api/web-smells` | `{directory}` | Web anti-pattern detection |
| POST | `/api/test-gen` | `{directory}` | Generate pytest stubs |
| POST | `/api/remediation-time` | `{findings}` | Estimate fix time per finding |
| POST | `/api/typecheck-pyright` | `{directory}` | Run pyright type checker (alternative to ty) |
| POST | `/api/connection-test` | `{directory}` | Analyze web framework route wiring |

### PM Dashboard

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/risk-heatmap` | `{directory, findings}` | Per-file composite risk scores |
| POST | `/api/module-cards` | `{directory, findings}` | Per-directory A-F grade cards |
| POST | `/api/confidence` | `{directory, findings}` | Release confidence 0-100% |
| POST | `/api/sprint-batches` | `{findings, smells}` | ROI-sorted sprint work packages |
| POST | `/api/architecture` | `{directory}` | Import graph + circular deps + layers |
| POST | `/api/call-graph` | `{directory}` | AST-based function call graph |
| POST | `/api/circular-calls` | `{directory}` | Function-level circular call detection |
| POST | `/api/coupling` | `{directory}` | Module coupling/cohesion metrics |
| POST | `/api/unused-imports` | `{directory}` | AST-based unused import detection |

### Utility

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/api/chat` | `{message}` | Knowledge-based chatbot (rules, tools, features) |
| POST | `/api/project-review` | `{directory, findings, smells, ...}` | Comprehensive project review |
| POST | `/api/monkey-test` | `{directory}` | Random endpoint testing |
| POST | `/api/wire-test` | `{directory}` | Web framework route wiring tests |
| GET | `/api/wire-progress` | | Poll wire-test progress |
| GET | `/api/monkey-progress` | | Poll monkey-test progress |

---

## 15. All Analyzer Functions Reference

Located in `analyzers/` package (11 sub-modules). Each function can be called programmatically or via its API endpoint.

| Function | Input | Returns |
|----------|-------|---------|
| `check_format(directory)` | directory path | `{needs_format, files[], all_formatted}` |
| `check_project_health(directory)` | directory path | `{score, passed, total, checks[]}` |
| `run_bandit(directory)` | directory path | `{bandit_issues[], secrets[], total_issues}` |
| `detect_dead_functions(directory)` | directory path | `{dead_functions[], total_defined, total_dead, total_called}` |
| `detect_duplicates(directory)` | directory path | `{duplicate_groups[], total_groups, total_duplicated_blocks}` |
| `analyze_temporal_coupling(directory)` | directory path | `{couplings[], total_commits, total_pairs}` |
| `detect_code_smells(directory)` | directory path | `{smells[], total, by_type{}}` |
| `check_types(directory)` | directory path | `{total_diagnostics, errors, warnings, diagnostics[], clean}` |
| `check_release_readiness(directory)` | directory path | `{score, passed, total, checks[], ready}` |
| `detect_ai_code(directory)` | directory path | `{indicators[], total, note}` |
| `detect_web_smells(directory)` | directory path | `{smells[], total, by_severity{}}` |
| `generate_test_stubs(directory)` | directory path | `{total_functions, tested, untested, coverage_pct, stubs[]}` |
| `estimate_remediation_time(findings)` | findings list | `{total_minutes, total_hours, per_finding[]}` |
| `compute_risk_heatmap(directory, findings)` | directory + findings | `{files[], total_files, max_risk, high_risk, medium_risk, low_risk}` |
| `compute_module_cards(directory, findings)` | directory + findings | `{modules[], total_modules}` |
| `compute_confidence_meter(directory, findings)` | directory + findings | `{confidence, checks[], passed, total, top_risks[], recommendation}` |
| `compute_architecture_map(directory)` | directory path | `{nodes[], edges[], layers{}, circular_deps[], god_modules[], clusters{}}` |
| `compute_call_graph(directory)` | directory path | `{nodes[], edges[], entries[], leaves[], total_functions, total_edges}` |
| `compute_sprint_batches(findings, smells)` | findings + smells lists | `{batches[], total_items, total_hours}` |
| `compute_project_review(directory, ...)` | directory + optional findings/smells/health/satd | `{sections[], overall_grade, summary}` |
| `detect_circular_calls(directory)` | directory path | `{circular_calls[], total_cycles, recursive_functions[], total_recursive, hub_functions[], total_hubs, total_functions, total_edges}` |
| `compute_coupling_metrics(directory)` | directory path | `{modules[], total_modules, health_summary{}, avg_instability, god_modules[], fragile_modules[], isolated_modules[]}` |
| `detect_unused_imports(directory)` | directory path | `{unused_imports[], total_unused, files_with_unused, by_file{}}` |

---

## 16. Configuration & Environment

### Server Configuration

```bash
# Default: localhost only, port 8077
python ui_server.py

# Custom port
python ui_server.py --port 9000

# Expose on network (caution: no auth)
python ui_server.py --host 0.0.0.0 --port 8077
```

### LLM Model Configuration (.env)

Required only for the agent auto-fix loop and LLM-powered test generation:

```bash
XRAY_MODEL_PATH=/path/to/model.gguf    # Path to GGUF model file
XRAY_N_CTX=8192                         # Context window size
XRAY_GPU_LAYERS=-1                      # GPU offload (-1 = all layers)
XRAY_TEMPERATURE=0.3                    # Low temperature for code generation
XRAY_MAX_TOKENS=2048                    # Max output tokens
```

### Security & Access Configuration

```bash
# Restrict file browser to specific directories (comma-separated)
# Default: project root + user home directory
# Set to empty string for unrestricted access
XRAY_BROWSE_ROOTS=/home/user/projects,/opt/code

# Enable CORS for cross-origin requests (e.g. from a frontend dev server)
# Use "*" for any origin. Leave unset to disable CORS.
XRAY_CORS_ORIGIN=http://localhost:3000
```

### Recommended LLM Models

| Model | Size | Speed | Quality | Best For |
|-------|------|-------|---------|----------|
| Qwen2.5-Coder-32B-Q4_K_M | 19 GB | ★★☆ | ★★★ | Best quality fixes |
| DeepSeek-Coder-V2-Lite-Q4 | 9 GB | ★★★ | ★★☆ | Fastest inference |
| Codestral-22B-Q4_K_M | 13 GB | ★★☆ | ★★★ | Balanced choice |

### Project Dependencies

```
# Core (always needed)
pytest >= 7.0

# Astral toolchain (recommended — fast, Rust-based)
uv           # Package/tool manager (optional but recommended)
ruff         # Format + Ruff Fix tools (managed by uv)
ty           # Type Check tool — Astral's Rust-based type checker (managed by uv)

# Other analysis tools (optional)
bandit       # Bandit Security tool

# For agent auto-fix (optional)
llama-cpp-python >= 0.3.0
```

---

## 17. Testing

### Run All Tests

```bash
python -m pytest tests/ -v
```

### Test Files (1013 tests, 999 passing + 14 skipped)

| File | Tests | What It Tests |
|------|------:|---------------|
| `tests/test_agent_loop.py` | 12 | Agent SCAN→TEST→FIX→VERIFY→LOOP cycle, AgentConfig, AgentReport |
| `tests/test_analyzers.py` | 25 | All 11 analyzer modules: health, smells, graph, connections, detection, etc. |
| `tests/test_build.py` | 35 | Rust build system, cross-compilation, binary discovery |
| `tests/test_compat.py` | 58 | Python/dependency/API/PyPI freshness checker |
| `tests/test_compat_stress.py` | 64 | Stress & edge cases for compat checker |
| `tests/test_comprehensive.py` | 107 | Broad coverage: rules, scanner accuracy, false-positive avoidance |
| `tests/test_config.py` | 26 | XRayConfig defaults, pyproject.toml loading, validation |
| `tests/test_connection_analyzer.py` | 22 | API endpoint & external connection detection |
| `tests/test_e2e_real.py` | 95 | **E2E (no mocks):** scanner, fixer, agent, all 46 API routes, services, SARIF, analyzers, rules, full workflow |
| `tests/test_false_positives.py` | 25 | String/comment-aware scanning; known false-positive regression |
| `tests/test_fixer.py` | 14 | 7 deterministic fixers + LLM fallback; preview vs apply |
| `tests/test_fixer_regression.py` | 22 | Fixer regression suite — no fix must break valid code |
| `tests/test_http_integration.py` | 24 | HTTP server bootstrap, all 46 REST endpoint responses |
| `tests/test_llm_mock.py` | 20 | LLM inference mock — deterministic fixer fallback |
| `tests/test_monkey.py` | 158 | Monkey-patch stress tests; edge cases for all 42 rules |
| `tests/test_portability.py` | 20 | PORT-001–004 rules: os.path, platform, encoding, line endings |
| `tests/test_sarif.py` | 24 | SARIF output schema, roundtrip, empty/partial findings |
| `tests/test_sca.py` | 14 | Software composition analysis (pip-audit integration) |
| `tests/test_scanner_boundary.py` | 77 | Scanner boundary & correctness: nested dirs, excludes, unicode, symlinks |
| `tests/test_ui_paths.py` | 40 | Path normalization, directory browsing, HTML escaping, dotfile filtering |
| `tests/test_verify.py` | 84 | Does-no-harm (SHA-256 check), finds-real-bugs, binary/huge-file edge cases |
| `tests/test_xray.py` | 47 | Rule database integrity (42 rules), scanner accuracy, language detection |

### Self-Scan

X-Ray scans its own codebase as a CI check:

```bash
python -m pytest tests/test_verify.py -v
```

This verifies that:
- Scanning **never modifies** source files (SHA-256 hash check before vs after)
- Every rule fires on its corresponding vulnerable code sample
- Edge cases (empty files, binary files, symlinks) are handled gracefully

---

## 18. File Map

```
X_Ray_LLM/
├── ui_server.py          # Thin HTTP dispatcher (31+ REST endpoints, port 8077)
├── ui.html               # Single-page web UI (28+ views)
├── build.py              # Rust build system + cross-compilation
├── setup_tools.py        # First-time bootstrap (installs uv, ruff, ty)
├── update_tools.py       # One-command updater for uv + ruff + ty
├── Run_me.bat            # Windows launcher (uses uv when available)
├── run.sh                # Linux/macOS launcher
├── README.md             # Project README
├── X_RAY_LLM_GUIDE.md   # This document
├── pyproject.toml        # Project configuration (ruff + ty config)
├── Dockerfile            # Docker deployment
├── docker-compose.yml    # Docker Compose config
├── MANIFEST.in           # PyPI source distribution manifest
│
├── xray/                 # Core scanner package
│   ├── __init__.py
│   ├── scanner.py        # Python scanning engine (string/comment-aware + AST validators)
│   ├── compat.py         # Python/dependency/API/PyPI freshness compatibility checker
│   ├── agent.py          # SCAN→TEST→FIX→VERIFY→LOOP orchestrator + CLI
│   ├── llm.py            # LLM inference (llama-cpp-python)
│   ├── fixer.py          # 7 deterministic auto-fixers + LLM fallback
│   ├── runner.py         # Test execution (pytest)
│   ├── sarif.py          # SARIF output format (GitHub Code Scanning)
│   ├── config.py         # XRayConfig from pyproject.toml
│   ├── constants.py      # Shared constants (SKIP_DIRS, file extensions)
│   ├── types.py          # TypedDict definitions for API responses
│   ├── sca.py            # Software Composition Analysis (pip-audit)
│   ├── wire_connector.py # Web framework route wiring analysis
│   ├── portability_audit.py # Cross-platform portability checker
│   └── rules/
│       ├── __init__.py   # Exports ALL_RULES (42 total)
│       ├── security.py   # SEC-001 through SEC-014 (14 rules)
│       ├── quality.py    # QUAL-001 through QUAL-013 (13 rules)
│       ├── python_rules.py  # PY-001 through PY-011 (11 rules)
│       └── portability.py   # PORT-001 through PORT-004 (4 rules)
│
├── analyzers/            # Analysis functions package (11 sub-modules)
│   ├── __init__.py       # Re-exports all 23+ public functions
│   ├── _shared.py        # Shared helpers: _walk_py, _walk_ext, _safe_parse
│   ├── format_check.py   # check_format, check_types, run_typecheck
│   ├── health.py         # check_project_health, estimate_remediation_time, etc.
│   ├── security.py       # run_bandit
│   ├── smells.py         # detect_dead_functions, detect_code_smells, detect_duplicates
│   ├── temporal.py       # analyze_temporal_coupling
│   ├── detection.py      # detect_ai_code, detect_web_smells, generate_test_stubs
│   ├── pm_dashboard.py   # Risk heatmap, module cards, confidence, sprint batches, etc.
│   ├── graph.py          # detect_circular_calls, compute_coupling_metrics, detect_unused_imports
│   └── connections.py    # analyze_connections (web framework wiring)
│
├── services/             # Business logic layer
│   ├── app_state.py      # Thread-safe AppState singleton
│   ├── scan_manager.py   # Scan orchestration, browse, Rust/Python engines
│   ├── git_analyzer.py   # Git hotspots, import parsing, ruff integration
│   ├── chat_engine.py    # Knowledge chatbot, guide loading
│   └── satd_scanner.py   # Self-Admitted Technical Debt scanning
│
├── api/                  # HTTP route modules
│   ├── scan_routes.py    # /api/scan, /api/abort, /api/scan-progress, /api/scan-result
│   ├── fix_routes.py     # /api/preview-fix, /api/apply-fix, /api/apply-fixes-bulk
│   ├── analysis_routes.py # 19 analysis POST endpoints
│   ├── pm_routes.py      # 13 PM Dashboard + utility POST endpoints
│   └── browse_routes.py  # /api/browse, /api/info, /api/env-check, /api/dependency-check
│
├── scanner/              # Optional Rust scanner
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs       # CLI entry point
│       ├── lib.rs        # Core engine (scan_directory, detect_lang)
│       └── rules/        # Rust rule implementations
│
├── docs/                 # Documentation
│   └── TESTING.md        # Complete testing guide (all 22 test files, CI pipeline)
│
└── tests/                # Test suite (1013 collected, 999 passing + 14 skipped)
    ├── test_xray.py           # Rule DB + scanner tests
    ├── test_verify.py         # Does-no-harm + finds-real-bugs
    ├── test_ui_paths.py       # Path handling + browse restrictions
    ├── test_e2e_real.py       # 95 end-to-end tests (no mocks)
    ├── test_analyzers.py      # Analyzer function tests
    ├── test_compat.py         # Version/dependency compatibility tests
    ├── test_compat_stress.py  # Stress tests for compatibility
    ├── test_http_integration.py # Real HTTP server integration tests
    ├── test_connection_analyzer.py # Web framework wiring tests
    ├── test_fixer.py          # Auto-fixer tests
    ├── test_fixer_regression.py # Fixer quality assurance
    ├── test_false_positives.py  # False positive regression tests
    ├── test_portability.py    # PORT-* rules tests
    ├── test_sarif.py          # SARIF output tests
    ├── test_sca.py            # SCA analysis tests
    ├── test_config.py         # Config loading tests
    ├── test_scanner_boundary.py # Scanner edge cases
    ├── test_agent_loop.py     # Agent pipeline tests
    ├── test_build.py          # Rust build tests
    ├── test_llm_mock.py       # LLM mock tests
    └── test_monkey.py         # Monkey/integration tests
```

---

## 19. Troubleshooting & FAQ

### Q: The scan returns zero findings on my project

**A**: Check that:
- The directory path is correct and contains `.py`, `.js`, `.ts`, or `.html` files
- You haven't set `--severity HIGH` which filters out MEDIUM/LOW findings
- The exclude patterns aren't filtering out all files

### Q: Ruff / Bandit / Type Check tool shows "not installed"

**A**: Install the missing tools:
```bash
python setup_tools.py          # Installs uv, ruff, and ty automatically
# Or manually:
uv tool install ruff ty        # Recommended
pip install ruff bandit        # Bandit via pip
```
Each tool button in the UI requires its corresponding package.

### Q: The Rust scanner doesn't appear in the engine selector

**A**: Build it first with `python build.py`. The UI auto-detects the binary at
`scanner/target/release/xray-scanner*`.

### Q: Can I scan non-Python projects?

**A**: Yes. X-Ray LLM scans Python, JavaScript, TypeScript, and HTML files. The security rules
(XSS, innerHTML, eval) target JavaScript/HTML as well. Some analysis tools (smells, dead code,
call graph, type check) are Python-specific.

### Q: How do I run the PM Dashboard from code?

**A**: Import and call the functions directly:

```python
from analyzers import (
    compute_risk_heatmap,
    compute_module_cards,
    compute_confidence_meter,
    compute_sprint_batches,
    compute_architecture_map,
    compute_call_graph,
    detect_circular_calls,
    compute_coupling_metrics,
    detect_unused_imports,
)

risk = compute_risk_heatmap("/path/to/project", findings=[])
cards = compute_module_cards("/path/to/project", findings=[])
confidence = compute_confidence_meter("/path/to/project", findings=[])
batches = compute_sprint_batches(findings=[], smells=[])
arch = compute_architecture_map("/path/to/project")
cg = compute_call_graph("/path/to/project")
circular = detect_circular_calls("/path/to/project")
coupling = compute_coupling_metrics("/path/to/project")
unused = detect_unused_imports("/path/to/project")
```

### Q: What files does the scanner skip?

**A**: By default: `__pycache__`, `.git`, `node_modules`, `venv`, `.venv`, `env`,
`.tox`, `.mypy_cache`, `dist`, `build`, `*.egg-info`, and binary files.

### Q: The confidence meter gives a low score — how do I improve it?

**A**: Look at the failed checks (shown with ❌). The most impactful improvements are usually:
1. **Fix security findings** (worth 20 points)
2. **Increase test coverage** (15 points)
3. **Fix circular dependencies** (10 points)
4. **Reduce code smells** (10 points)

The Sprint Batches tool will prioritize these automatically by ROI.

---

*This document is the complete reference for X-Ray LLM. Every feature, endpoint, analyzer,
rule, and UI capability is described here. For the latest code, see the source files listed
in the File Map section.*
