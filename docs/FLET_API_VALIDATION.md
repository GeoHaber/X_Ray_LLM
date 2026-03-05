# Flet API Pre-Launch Validation

## Problem
Flet 0.80.2 introduced API breaking changes that only surfaced at runtime, causing crashes that were discovered by testing the UI rather than through static analysis.

## Solution
Created a static validation tool (`.github/scripts/validate_flet_api.py`) that checks for deprecated/invalid Flet parameters BEFORE running the app.

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
