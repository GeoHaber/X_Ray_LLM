# Transpiler Error Reduction - Phase Status

## Current State (Feb 26, 2026)

**Baseline Errors**: 35,016 (after v5.1.3)
**Current Errors**: 35,011 (-5 net improvement)

### Phase 1: Enhanced Type Inference ❌ FAILED - REVERTED
- **Approach**: Expanded `_NAME_TYPE_RULES` with 25+ keyword patterns + body AST analysis via `_analyze_param_types_from_body()`
- **Result**: +43 errors (35,016 → 34,750 then back up to 35,059), **regression**
- **Root Cause**: 
  - Substring matching in name inference too aggressive (e.g., "id" in "model_id" → forced to i64)
  - Body analysis used overly broad defaults (Vec<String>, HashMap<String,String>) instead of generic types
  - Variable names had conflicting inferences
- **Status**: REVERTED via `git checkout Analysis/transpiler.py`

### Phase 2: Stdlib Mapping Database ✅ SUCCESSFUL
- **Approach**: Expanded `_METHOD_RENAMES` from 8 → 40+ method name mappings across String/Vec/HashMap
- **Changes**:
  - Added capitalize, title, isdigit, isalpha, isalnum, isspace, find, rfind, etc.
  - Added extend, remove, clear, insert, reverse, sort, copy, keys, values, update, setdefault
- **Result**: -5 errors (35,016 → 35,011)
  - E0599 (method not found): -86 ✓ (1,663 → 1,577)
  - E0308 (type mismatch): +25 (side effect of corrections exposing typing issues)
- **Status**: DEPLOYED - git commit `9bada49`

### Phase 3: Auto .clone() Insertion ❌ FAILED - REVERTED
- **Approach**: Modified `_expr_subscript()` and `_dispatch_method_call()` to auto-insert `.clone()` for borrow checker
- **Attempts**:
  1. HashMap subscript access auto-clone heuristic
  2. .get() → .cloned() auto-wrap
  3. String methods (trim, upper, lower) → .to_string() suffix
- **Result**: +2 errors (35,011 → 35,018), **regression**
- **Root Cause**: Aggressive cloning introduces unnecessary moves, causes more type mismatches / trait bound failures
- **Status**: REVERTED via git checkout before commit

## Error Profile (Current: 35,011)

```
E0425: 21,669 (61.9%) - cannot find value (unfixable: class→function extraction limits)
E0308:  5,297 (15.1%) - type mismatch (fixable with better type inference)
E0277:  1,694 (4.8%)  - trait not implemented (fixable with stdlib mapping)
E0599:  1,577 (4.5%)  - method not found (REDUCED by Phase 2)
E0609:  1,461 (4.2%)  - field not found (fixable with better struct inference)
E0282:    870 (2.5%)  - type annotation needed (fixable)
E0369:    678 (1.9%)  - invalid operator (fixable)
E0600:    344         - invalid operator on ref (fixable)
E0728:    198         - await outside async (architectural)
E0689:    192         - too many args (fixable)
E0608:    136         - improper struct (fixable)
[others]:  295        - miscellaneous
```

## Next Steps (For Restart)

### Phase 4 Candidates (in priority order):

1. **String vs &str Normalization** (~500-1000 errors fixable)
   - Auto-insert `.to_string()` on String type mismatches
   - Auto-insert `.as_str()` on &str type mismatches
   - Fix E0308 type mismatches more intelligently

2. **Operator Overload Handling** (~500-678 errors fixable)
   - E0369: Implement fmt::Add/Sub/Mul/Div/ for custom types
   - E0600: Better handling of reference operators in arithmetic

3. **Borrow-Aware Type Inference** (conservative approach)
   - Instead of aggressive cloning, improve parameter annotations
   - Use move semantics strategically instead of borrowing
   - Detect when Vec<T> should be &[T], etc.

4. **AST-Based Type Tracking** (expensive but effective)
   - Build a symbol table during transpilation
   - Track variable types through assignments and method calls
   - Apply multi-pass transpilation if needed

### Testing Procedure for Next Phase:
```bash
# Make changes to Analysis/transpiler.py
python _scratch/retranspile_pairs.py                    # Quick retranspilation
if (Test-Path _verify_crate\target\debug\incremental) { Remove-Item _verify_crate\target\debug\incremental -Recurse -Force } 
python verify_rust_compilation.py                       # Full verification (~10min)
```

### CI/Testing
- **Tier-3 Tests** (35/35): Still passing - no regression from Phase 2
- **Tier-4 Tests** (24/24): Not run recently - verify next restart
- **Pytest** (166 tests): Core logic passes
- **Full Verification** (6,643 pairs): Last run 35,011 errors, Phase 2 deployed

## Key Learnings

✗ **What doesn't work**:
  - Aggressive substring matching for type inference (too many false positives)
  - Broad defaults for collection element types (should infer or stay generic)
  - Auto-cloning as a borrow fix (exposes more typing issues than it fixes)

✓ **What works**:
  - Method name mapping (Phase 2 reduced E0599 errors)
  - Targeted keyword matching for specific knowledge domains (crypto, auth types)
  - Explicit stdlib translations (Path, dict, etc.)

## Git Status
- Branch: master
- Commits: 9bada49 (Phase 2) latest
- Uncommitted: None (Phase 3 reverted)

---
**Next session**: Start with Phase 4, consider String/&str normalization first (lowest risk, high impact).
