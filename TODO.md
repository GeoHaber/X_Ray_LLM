# X_Ray — TODO

> Last updated: 2026-03-11

---

## ✅ Bugs Found & Fixed (this session)

All four bugs below have the same root cause: **auto-generated module-level compatibility wrappers** attempt to instantiate `@dataclass` or `Enum` types with zero arguments, which crashes because those types require positional parameters.

### 1. `Lang/js_ts_analyzer.py` — IndentationError (line ~770)
- **Symptom**: `IndentationError: unexpected indent` when importing the module
- **Cause**: `return _default_analyzer.location(...)` was indented one level too deep inside the `location()` wrapper function
- **Fix**: Removed the extra indentation level

### 2. `Lang/js_ts_analyzer.py` — `JSFunction()` singleton (line ~766)
- **Symptom**: `TypeError: JSFunction.__init__() missing 14 required positional arguments`
- **Cause**: `_default_analyzer = JSFunction()` — `JSFunction` is a `@dataclass` with 14 required fields (name, file_path, line_start, line_end, params, return_type, body_lines, complexity, nesting_depth, is_async, is_generator, is_arrow, is_method, decorators)
- **Fix**: Removed the broken singleton; created standalone `location(file_path, line_start)` function instead

### 3. `Analysis/project_health.py` — `HealthCheck()` singleton (line ~522)
- **Symptom**: `TypeError: HealthCheck.__init__() missing 3 required positional arguments: 'name', 'description', 'weight'`
- **Cause**: `_default_analyzer = HealthCheck()` — `HealthCheck` is a `@dataclass(frozen=True)` with 3 required fields
- **Fix**: Replaced singleton with `NotImplementedError` stubs for `analyze()`, `summary()`, `to_dict()`

### 4. `Analysis/release_readiness.py` — `MarkerHit()` singleton (line ~620)
- **Symptom**: `TypeError: MarkerHit.__init__() missing 5 required positional arguments`
- **Cause**: `_default_analyzer = MarkerHit()` — `MarkerHit` is a `@dataclass` with 5 required fields (marker, file_path, line_no, context, severity)
- **Fix**: Replaced singleton with `NotImplementedError` stubs

---

## 🔲 TODO — Remaining Broken `_default_analyzer` Singletons

**6 more files** have the identical pattern — `_default_analyzer = SomeDataclass()` at module level — and will crash when that code path is executed. Same fix pattern needed: replace with standalone functions or `NotImplementedError` stubs.

| # | File | Broken Class | Type | Required Args |
|---|------|-------------|------|---------------|
| 1 | `Lang/model_analyzer.py` | `ModelCategory()` | **Enum** | N/A (Enums can't be instantiated with `()`) |
| 2 | `Lang/model_analyzer.py` | `IOSample()` | @dataclass | 4 (name, input_data, expected_output, description) |
| 3 | `Lang/ui_analyzer.py` | `UICallSite()` | @dataclass | 10 (file, line, col, framework, component, props, children_count, is_conditional, parent_component, nesting_depth) |
| 4 | `Lang/ui_analyzer.py` | `UIHealthIssue()` | @dataclass | 6 (category, severity, message, file, line, suggestion) |
| 5 | `Analysis/verification_engine.py` | `VerificationAnalyzer()` | @dataclass | 1 (rules) |
| 6 | `Lang/model_analyzer.py` | `ModelCard()` | @dataclass | 14 (name, framework, format, task, architecture, parameters, input_shape, output_shape, preprocessing, postprocessing, metrics, labels, metadata, io_samples) |

### Suggested Fix Pattern
For each broken file:
1. Remove `_default_analyzer = BrokenClass()` line
2. For each wrapper function that delegates to `_default_analyzer.method(...)`:
   - Either implement as standalone function, or
   - Raise `NotImplementedError("Use BrokenClass directly with required args")`
3. Verify module imports cleanly with `python -c "import X_Ray.Lang.model_analyzer"`

### Root Cause
These appear to be **auto-generated compatibility shims** — a code generator created module-level singleton instances + wrapper functions for every dataclass, without checking whether the class constructor requires arguments. The 17 classes with zero-arg constructors work fine; only `@dataclass` types and `Enum` types without defaults break.

---

## 🔲 TODO — Other Improvements

- [ ] **Add a test suite for the singleton wrappers** — Many of the 23 `_default_analyzer` patterns across the codebase are never tested. A simple import test for each module would catch these crashes.
- [ ] **Review code generator** — If these wrappers are auto-generated, fix the generator to skip `@dataclass` types that require positional args, or generate factory functions with proper defaults.
- [ ] **Add CI/CD smoke test** — `python -c "from X_Ray import *"` or equivalent to catch import-time crashes before release.
