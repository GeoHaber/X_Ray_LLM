# Flet API Pre-Launch Validation

## Problem
Flet 0.80.x introduced API breaking changes that only surfaced at runtime, causing crashes that were discovered by testing the UI rather than through static analysis.

## Runtime Version Gate (v7.2)

As of v7.2, `x_ray_flet.py` includes an automatic version gate that runs at startup:

```python
_MIN_FLET = (0, 80, 0)

def _check_flet_version() -> None:
    from packaging.version import Version
    installed = Version(ft.__version__)
    required  = Version(".".join(str(p) for p in _MIN_FLET))
    if installed >= required:
        return
    # auto-upgrade via pip, then exit with restart message
```

If Flet is older than 0.80.0, the gate auto-runs `pip install flet>=0.80.0` and
asks the user to restart. This prevents all of the breaking-change crashes below.

## Static Validation Tool

A static validation tool (`.github/scripts/validate_flet_api.py`) checks for deprecated/invalid Flet parameters BEFORE running the app.

## Usage

### Check before launching Flet UI
```bash
python .github/scripts/validate_flet_api.py
```

### Add to CI/CD pipeline
```bash
python .github/scripts/validate_flet_api.py || exit 1
```

### Exit codes
- `0` = All checks passed, safe to launch
- `1` = Issues found, fix before running

## What it detects

### 1. TextField/Text font_family deprecation
**Invalid:**
```python
ft.TextField(font_family=MONO_FONT)  # ERROR in 0.80.2
ft.Text(font_family=FONT)            # ERROR in 0.80.2
```

**Correct:**
```python
ft.TextField(text_style=ft.TextStyle(font_family=MONO_FONT))
ft.Text(style=ft.TextStyle(font_family=FONT))
```

### 2. Border.left() removal
**Invalid:**
```python
border=ft.Border.left(4, color)  # ERROR in 0.80.2
```

**Correct:**
```python
border=ft.Border.only(left=ft.BorderSide(4, color))
```

### 3. Padding.symmetric() positional args
**Invalid:**
```python
padding=ft.Padding.symmetric(6, 10)  # ERROR: positional args
```

**Correct:**
```python
padding=ft.Padding.symmetric(vertical=6, horizontal=10)
```

## Integration

Add to recommended pre-launch checklist:
```bash
# Pre-Flet launch validation
python .github/scripts/validate_flet_api.py && \
python x_ray_flet.py
```

## Future improvements
- Add AST-based param validation for more accuracy
- Integrate with Pyright type checking for Flet stubs
- Add per-version API tracking for multiple Flet versions
- Auto-fix common issues

## Additional Flet 0.80 Breaking Changes (discovered in v7.2)

| Change | Impact | Fix applied |
|--------|--------|-------------|
| `ft.Icons.*` enums are **ints**, not strings | `section_title()` and `metric_tile()` rendered raw int codepoints or blank cards | Type-check icon; use `ft.Icon()` widget for non-string icons |
| `ft.alignment.center` removed | `_empty_state()` crashed | Use `ft.Alignment(0, 0)` |
| `ft.ElevatedButton` deprecated (since 0.70) | Deprecation warnings in every tab | Replace with `ft.Button` |
| `ft.Button` first param is `content` (StrOrControl) | No `.text` attribute; auto-wraps strings | Access `.content` instead of `.text` |
| Sync `on_click` blocks Flet event loop | Nexus / Auto-Rustify buttons froze the UI | Use `async def` handler + `loop.run_in_executor()` |
