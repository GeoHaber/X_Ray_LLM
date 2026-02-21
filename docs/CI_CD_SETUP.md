# Automated Code Quality CI/CD Setup

> **Philosophy:** Less is more. Simple automated checks that keep quality high without friction.

## What's Included

✅ **GitHub Actions Workflows** — Automated testing + code quality on every push/PR  
✅ **Pre-commit Hook** — Local smell detection before committing  
✅ **Quality Gates** — Configurable thresholds that fail builds when violated  
✅ **Self-documenting** — X-Ray analyzes itself  

---

## 3-Step Setup

### 1. GitHub Actions (CI/CD Pipeline)

The workflow file `.github/workflows/quality.yml` runs automatically on:
- Push to `main` or `develop`
- All pull requests

**What it does:**
```
pytest → ✅ Tests pass
         ↓
x_ray_claude.py → Generate smell report
                  ↓
check_quality.py → Parse report, check gates
                   ↓
Quality Gate {PASS/FAIL}
```

**No additional setup needed** — just merge to `main`!

### 2. Local Pre-commit Hook

Run X-Ray smell detection **before** you commit:

```bash
# One-time setup
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Then every commit runs:
```bash
python x_ray_claude.py --smell --path .
```

**Skip if needed:** `git commit --no-verify`

### 3. Manual Scans

Whenever you want to check code quality:

```bash
# Full analysis + JSON report
python x_ray_claude.py --full-scan --path . --report scan.json

# Code smells only (faster)
python x_ray_claude.py --smell --path .

# Generate interactive graph
python x_ray_claude.py --full-scan --graph --path .
```

---

## Quality Gates (Configurable)

Edit `.github/scripts/check_quality.py` to adjust thresholds:

```python
QUALITY_GATES = {
    "max_critical_smells": 20,      # Fail if > 20 critical issues
    "max_long_functions": 25,       # Fail if > 25 functions > 120 lines
    "max_complex_functions": 30,    # Fail if > 30 functions with complexity > 20
    "max_total_smells": 200,        # Fail if > 200 total smells
    "max_duplicate_groups": 50,     # Warn if > 50 duplicate groups
}
```

**Current Status:** X-Ray itself: 148 smells, 16 critical (your own code!)

---

## Artifact Reports

Each CI run uploads 2 artifacts:

1. **test-results.xml** — Pytest results (JUnit format)
2. **code-quality-report/**
   - `x_ray_report.json` — Full analysis
   - `quality-check.log` — Gate check summary

Download from GitHub Actions → Artifacts tab.

---

## Example Workflow

### During Development
```bash
# Make changes
git add .
git commit -m "Refactor duplicates"
# ↓ Pre-commit hook runs X-Ray
# ✅ Passes → commit succeeds
# ❌ Fails → review smells, fix, try again
```

### On Pull Request
```bash
git push origin feature-branch
# ↓ GitHub Actions runs:
#   - pytest tests/
#   - x_ray_claude.py --full-scan
#   - check_quality.py
# ✅ All pass → ready to merge
# ❌ Fails → see logs, make fixes, push again
```

### Monitoring Trends
Each merge to `main` generates a quality report. Track:
- 📈 Smells over time (should decrease)
- 🔄 Duplicates (opportunity for extraction)
- 🎯 Coverage (via complexity metrics)

---

## Customization

**Disable quality check for a commit:**
```bash
git commit --no-verify
```

**Adjust GitHub Actions trigger:**
Edit `.github/workflows/quality.yml` — change `on:` section

**Add more smells checks:**
Edit `x_ray_claude.py --smell --path .` to add custom rules

**Different Python versions:**
Change `matrix.python-version` in `quality.yml`

---

## Tips

💡 **Start permissive, tighten over time**
- High thresholds initially
- Gradually lower as you fix issues
- Reach a "quality baseline" you commit to

💡 **Use for code review**
- "This PR increases smells by X" (visible in artifacts)
- "Duplicates: before 20 → after 15" 

💡 **Integrate with IDE**
- VS Code: Install X-Ray plugin (if available)
- JetBrains: Run `x_ray_claude.py` in External Tools

---

## FAQ

**Q: CI is failing, what do I do?**  
A: Download the `code-quality-report` artifact, check `quality-check.log`, fix issues, push again.

**Q: Pre-commit hook is slow**  
A: Use `--smell` instead of `--full-scan` (1-2 sec vs 10 sec)

**Q: Can I adjust quality gates per repo?**  
A: Yes, edit `QUALITY_GATES` dict in `.github/scripts/check_quality.py`

**Q: What if tests pass but smells fail?**  
A: Build still fails (quality gate). Fix smells or adjust thresholds.

---

## Next Steps

1. ✅ Merge CI/CD files to `main`
2. ✅ Test with a dummy PR branch  
3. ✅ Adjust gates based on your codebase
4. ✅ Commit `.githooks/pre-commit` setup docs  
5. 🎯 Watch code quality improve over time!

