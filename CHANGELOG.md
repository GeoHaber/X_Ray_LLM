# Changelog

## v5.1.2 — Standalone EXE, Trial License & Duplicate Fix (2026-02-24)

### Overview
Shipped X-Ray as a **portable `.exe`** with an interactive wizard, hardware-locked
trial license system, and fixed a crash in the Rust-accelerated duplicate detector.

---

### Standalone EXE Distribution
- **Interactive wizard** for double-click usage (no terminal needed):
  1. Native Windows folder picker (tkinter)
  2. Scan mode menu (7 options: lint, smells, duplicates, security, full scan, etc.)
  3. Report prompt (JSON, console summary, or both)
- **Bundled tools**: ruff.exe, bandit.exe, x_ray_core.pyd, tkinter — all in one ~64 MB package
- **Auto-detection**: Detects double-click vs. CLI args → routes to wizard or standard CLI
- **Build**: `python -m PyInstaller x_ray.spec --noconfirm`

### Trial License System (Rust-Based)
Hardware-locked 10-run trial, entirely in compiled Rust:
- **Machine fingerprint**: SHA-256 of username + computer name + CPU count + OS + home dir
- **Encrypted counter**: AES-256-GCM with machine-derived key
- **Integrity check**: HMAC-SHA256 with separate derived key
- **Storage**: `%APPDATA%\x_ray\.xrl` (84 bytes binary)
- No server required — each new machine gets a fresh 10 runs
- All crypto in `x_ray_core.pyd` — no Python-side secrets to patch

### Bug Fixes

| Fix | Description |
|---|---|
| **Duplicate detection crash** | `prefilter_parallel` returns `(str, str, float)` key tuples but `_batch_code_similarity` expected `FunctionRecord` objects → `AttributeError: 'str' object has no attribute 'code'`. Fixed by resolving string keys back to objects via `func_map`. |
| **Double `code_similarity` call** | Python fallback path called `code_similarity(f1.code, f2.code)` twice per pair (filter + value). Replaced with walrus operator `:=` for single evaluation. |
| **Bandit missing from .exe** | `x_ray.spec` bundled ruff.exe but not bandit.exe → "bandit not found (skipped)" in .exe output. Added `bandit_path` to spec binaries. |
| **tkinter excluded from .exe** | Was in PyInstaller excludes list → folder picker crashed. Removed from excludes. |

### Rust↔Python Boundary Audit
Full audit of all 12 `#[pyfunction]` boundaries:
- 3 production-hot call sites verified: `code_similarity`, `batch_code_similarity`, `prefilter_parallel`
- Hash algorithm divergence noted (Rust FxHash vs Python SHA-256) — safe since paths are never mixed
- `Counter` → `FxHashMap<String, u32>` conversion verified safe (int-only values)
- `FunctionRecord.key` @property works with PyO3's `getattr` (invokes descriptors)

### Files Changed
- `Analysis/duplicates.py` — Fixed Rust prefilter key resolution + walrus operator optimization
- `x_ray_exe.py` — Interactive wizard (`_pick_folder`, `_interactive_menu`, `_needs_interactive`), trial license gate
- `x_ray_claude.py` — Trial license gate (silent fallthrough in dev mode)
- `x_ray.spec` — Added bandit.exe, removed tkinter from excludes
- `Core/x_ray_core/src/lib.rs` — Added `check_trial`, `trial_max_runs` pyfunctions
- `Core/x_ray_core/Cargo.toml` — Added sha2, hmac, aes-gcm, dirs dependencies
- `README.md` — Standalone EXE docs, trial license, lessons learned
- `CHANGELOG.md` — This entry

---

## v5.1.1 — Zero Syntax Errors: Cargo-Check-Verified Round 3+4 (2026-02-23)

### Overview
Eliminated **ALL syntax-class compilation errors** from transpiled Rust output.
Starting from **548 cargo check errors**, two targeted fix rounds reduced syntax
errors to **zero** across 7,071 clean functions (100,924 lines of Rust code from
15 real Python projects).

The remaining errors are exclusively **type/semantic** (E0308, E0425, E0599, etc.)
— a fundamentally different category requiring type inference, which is expected
for a syntax-focused transpiler operating on duck-typed Python.

---

### Round 3 — 548 → 4 syntax errors (−99.3 %)
| Fix | Target Pattern | Errors Fixed |
|---|---|---|
| Negative indexing `arr[-1]` → `arr[arr.len() - N]` | `cannot be used as negative numeric literal` | ~27 |
| Negative slice bounds `arr[:-1]`, `arr[-2:]` | Slice with negative indices | ~14 |
| For-loop `vec![a,b,c]` → `[a,b,c]` slice pattern | `arbitrary expressions in patterns` | ~172 |
| `println!` format literal safety | `format argument must be string literal` | ~15 |
| `_unwrap_format_args` placeholder count verification | `argument never consumed` / mismatch | ~205 |
| Non-literal `.format()` base fallback | Broken `format!(non_literal, args)` | ~57 |

### Round 4 — 4 → 0 syntax errors (100 % clean)
| Fix | Target Pattern | Errors Fixed |
|---|---|---|
| Dict `**unpacking` comment placement | `expected expression, found ','` after `/* **expr */` | 2 |
| `.count()` as-cast parenthesization | `cast cannot be followed by a method call` | 1 |
| Non-literal `.format()` no trailing block comment | `unterminated block comment` inside macros | 1 |

### Error Landscape After Fixes
With all syntax errors eliminated, `rustc` now proceeds to full type-checking:

| Category | Count | Examples |
|---|---|---|
| **Syntax errors** | **0** | — |
| Type errors (E0308, E0277, E0369) | 211 | `expected i64, found usize` |
| Semantic errors (E0425, E0609, E0599) | 241 | `cannot find function`, `no field` |
| Other (E0282, E0384) | 47 | Type inference, mutability |

All 8 original syntax error categories verified as **FIXED**:
`expected expression ','`, `arbitrary expressions`, `unknown character escape`,
`negative numeric literal`, `expected comma`, `unterminated block comment`,
`format argument must be literal`, `invalid format string`.

### Coverage Update
| Metric | Before | After |
|---|---|---|
| Clean pairs | 6,917 | 7,071 |
| Total pairs | 7,694 | 7,849 |
| Scanned projects | 14 | 15 |
| Syntax errors | 548 | **0** |
| Transpilable rate | 54.7 % | 55.8 % |

### Tests
All test suites pass: **81 tests** total.
- Tier-3 module handlers: 35 tests
- Tier-2 expansion: 13 tests
- Round-3 fixes: 13 tests
- Round-4 cargo-verified fixes: 20 tests

### Files Changed
- `Analysis/transpiler.py` — 9 function modifications across Rounds 3+4
- `_scratch/test_transpiler_round4.py` — New 20-test suite (new)
- `_scratch/test_round4_fixes.py` — Quick-check script (new)

---

## v5.1.0 — Transpiler Expansion & Cargo-Verified Fixes (2026-02-21)

### Overview
Major expansion of the Python → Rust transpiler covering **19 module handlers**,
async/await support, data-driven threshold tuning, and two rounds of
cargo-check-verified compilation fixes. Coverage across 14 real projects rose
from **30.8 %** to **53.2 %**, while compilation errors dropped **74 %+**.

---

### New Module Handlers (Tier 3)
| Module | Key Rust Mappings |
|---|---|
| `time` | `std::thread::sleep`, `std::time::Instant` |
| `datetime` | `chrono::Utc::now()`, `NaiveDate`, format specs |
| `timedelta` | `chrono::Duration` |
| `subprocess` | `std::process::Command` |
| `hashlib` | `sha2::Sha256`, `md5::Md5` |
| `argparse` | `clap::Command` / `Arg` |
| `collections` | `HashMap`, `VecDeque`, `BTreeMap` |
| `functools` | `lru_cache` → memoization comment, `partial` → closure |
| `itertools` | `itertools::chain`, `product`, `combinations` |
| `logging` | `log::info!` / `warn!` / `error!` / `debug!` |

Expanded existing handlers: **sys** (`sys.exit` → `std::process::exit`,
`sys.argv` → `std::env::args`, `sys.platform`, `sys.stdin`).

Added **async/await** transpilation (`async def` → `async fn`,
`await expr` → `expr.await`).

### Threshold Tuning (Data-Driven)
Analysed blocker distribution across 14 projects and raised limits:
- `unresolvable_calls`: 8 → **20**
- `external_calls`: 10 → **20**
- `max_lines`: 200 → **500**
- `mostly_strings`: 0.5 → **0.7**

Result: **7,485 / 14,064** functions now transpilable (was 4,322).

### Cargo-Check Verified Fixes

#### Round 1 — 3,446 → 892 errors (−74 %)
| Fix | Errors Fixed |
|---|---|
| Format-string double-wrap in `println!` / `log::*!` | ~1,237 |
| `let mut self.field` → bare assignment for attribute targets | ~750 |
| Comment-only fallback values (injected `todo!()`) | ~286 |
| `super` renamed to `super_` (cannot be raw identifier) | 86 |
| Datetime `%`-format specs stripped from Rust format strings | ~40 |
| Bytes literal escaping (`_escape_bytes_literal`) | ~30 |
| Positional placeholders `{0}` → `{}` in `.format()` | ~20 |
| `print()` single-arg literal detection improved | ~15 |

#### Round 2 — Additional pattern fixes
| Fix | Description |
|---|---|
| `_ensure_expr()` wrapper | Guarantees every expression context has a value; wraps comment-only results with `todo!()` |
| Applied `_ensure_expr` to | `if`/`elif`/`while` conditions, `for` iterators, `return` values, annotated assignments |
| Tuple unpacking with complex targets | `self.a, self.b = x` → individual `_destructured.N` assignments |
| `_` in destructure | Skips `mut` keyword for underscore targets |
| Keyword attribute escaping | `r#type`, `r#match`, etc. for reserved-word field access |
| `_expr()` comment injection | ALL comment-only handler results now get `todo!()` appended |
| `_expr_attribute` guard | Detects comment/todo chains and collapses to single `todo!()` |

### Verification Infrastructure
- **`scan_all_rustify.py`** — Scans all 14 projects, collects `pairs.jsonl`
  with Python→Rust function pairs and blocker statistics.
- **`verify_rust_compilation.py`** — Loads pairs, generates a Cargo crate
  with batch modules (200 functions each), runs `cargo check`, and maps
  errors back to source Python functions.
- **`_scratch/test_transpiler_tier3.py`** — 35 tests for Tier 3 handlers.
- **`_scratch/test_transpiler_expansion.py`** — 13 tests for Tier 2 handlers.

### Coverage Progression
| Stage | Transpilable | Total | Rate |
|---|---|---|---|
| Pre-Tier 3 | 4,322 | 14,044 | 30.8 % |
| Post-Tier 3 | 5,853 | 14,054 | 41.6 % |
| Post-Threshold Tuning | 7,485 | 14,064 | 53.2 % |
| Post-Round 2 Fixes | 7,694 pairs (6,917 clean) | 14,064 | 54.7 % |

### Tests
All test suites pass: **35** Tier-3 + **13** Tier-2 + **24** existing = **72 tests**.

### Files Changed
- `Analysis/transpiler.py` — Core transpiler (19 module handlers, 2 rounds of fixes)
- `Analysis/auto_rustify.py` — Blocker detection, threshold tuning
- `scan_all_rustify.py` — Multi-project scanner (new)
- `verify_rust_compilation.py` — Cargo-check verification harness (new)
- `_scratch/test_transpiler_tier3.py` — Tier 3 test suite (new)
- `_scratch/test_transpiler_expansion.py` — Tier 2 test suite (new)
- `.gitignore` — Excludes regeneratable artifacts
- `Core/utils.py`, `x_ray_exe.py` — Minor fixes
- `docs/` — Moved CI_CD_SETUP.md, added how_to_download_rust.md

---

## v5.0.0 — Initial Release
- Full Python AST → Rust transpiler with 9 module handlers
- Code smell detection, security analysis, duplicate finder
- Desktop (PyInstaller) and web (Flask) interfaces
- Mothership settings sync
