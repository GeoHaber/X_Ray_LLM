# X-Ray — Usage Guide

## Installation

Core scanning works with **Python 3.10+ stdlib only** — no install needed.

```bash
python x_ray_claude.py --help
```

For **full-scan** (lint, security, format), install: `pip install -r requirements.txt`  
For **testing**: `pip install pytest` (or `uv sync`)

---

## Command-Line Options

| Flag | Description |
|---|---|
| `--path PATH` | Root directory to scan (default: current directory) |
| `--smell` | Run code smell detection |
| `--duplicates` | Find cross-file function duplicates |
| `--suggest-library` | Suggest library extractions from duplicate groups |
| `--full-scan` | Run all features (smells, duplicates, lint, security, format, library, graph) |
| `--graph` | Generate interactive HTML graph |
| `--report FILE` | Save full JSON report to FILE |
| `--use-llm` | Enable LLM enrichment (requires Local LLM backend) |
| `--model-path PATH` | Path to LLM model file (overrides `XRAY_MODEL_PATH` env var) |
| `--max-llm-calls N` | Max LLM calls per feature (default: 20) |
| `--exclude DIR` | Directories to exclude (repeatable) |
| `--include DIR` | Only scan these directories (repeatable) |
| `-q, --quiet` | Minimal output |

---

## Usage Examples

### 1. Quick Smell Check

```bash
python x_ray_claude.py --smell --path ./my_project
```

Output shows detected code smells with severity icons:
- `[!!]` / 🔴 Critical — needs immediate attention
- `[!]` / 🟡 Warning — should be addressed
- `[i]` / 🟢 Info — nice to know

### 2. Find Duplicates

```bash
python x_ray_claude.py --duplicates --path ./my_project
```

Detects three types of duplicates:
- **Exact** — identical code (same SHA-256 hash)
- **Near** — structurally similar (cosine > 0.25 pre-filter AND SequenceMatcher > 0.7)
- **Semantic** — functionally similar (LLM-confirmed, requires `--use-llm`)

### 3. Library Extraction Suggestions

```bash
python x_ray_claude.py --suggest-library --path ./my_project
```

Groups related duplicates and suggests unified library modules with:
- Module name suggestion
- Unified API signature
- Rationale for extraction

### 4. Full Analysis with Graph

```bash
python x_ray_claude.py --full-scan --graph --path ./my_project
```

Generates an interactive HTML file (`xray_claude_graph.html`) with three tabs:
- **Graph** — vis-network force-directed graph with health-colored nodes
- **Duplicates** — Searchable, sortable duplicate list
- **Smells** — Filterable smell table

### 5. JSON Report for CI/CD

```bash
python x_ray_claude.py --full-scan --report results.json --path ./my_project
```

Produces a structured JSON report with all findings, suitable for:
- CI pipeline quality gates
- Trend tracking over time
- Integration with other tools

### 6. LLM-Enhanced Analysis

```bash
python x_ray_claude.py --full-scan --use-llm --path ./my_project

# Or specify a model path directly
python x_ray_claude.py --full-scan --use-llm --model-path /path/to/model.gguf --path ./my_project
```

When `--use-llm` is enabled, the analyzer:
1. Uses heuristics first (fast pre-filter)
2. Sends only flagged items to the LLM for deeper analysis
3. Gets severity ratings, refactoring suggestions, and design pattern advice

Requires a running Local LLM backend (`Core.services.inference_engine`).

---

## Understanding the Output

### Smell Categories

| Category | Description | Threshold |
|---|---|---|
| `long-function` | Function exceeds line limit | > 60 lines (warning) / > 120 (critical) |
| `god-class` | Class with too many methods | > 15 methods |
| `deep-nesting` | Excessive nesting depth | > 4 levels (warning) / > 6 (critical) |
| `complex-function` | High cyclomatic complexity | > 10 (warning) / > 20 (critical) |
| `too-many-params` | Too many function parameters | > 6 params |
| `missing-docstring` | Public function without docstring | functions > 15 lines |
| `too-many-returns` | Too many return statements | > 5 returns |
| `boolean-blindness` | Bool return without question-style name | — |
| `mutable-default-arg` | PEP 8: def f(x=[]) — mutable defaults cause bugs | — |
| `bare-except` | PEP 8: use specific exceptions, not bare `except:` | — |
| `complex-comprehension` | Nested list/dict comprehension (prefer explicit loops) | — |
| `utility-class-name` | Class named Common/Utils/Helper with many methods | ≥ 5 methods |
| `new-overuse` | Class defines both `__new__` and `__init__` | — |
| `large-class` | Class exceeds line limit | > 500 lines |
| `missing-class-docstring` | Class without docstring | classes > 30 lines |
| `dataclass-candidate` | Simple class that could be @dataclass | ≤ 3 methods, no bases |

### Similarity Scores

- **Token cosine** (0.0–1.0): Measures vocabulary overlap using TF-IDF vectors
- **Code similarity** (0.0–1.0): SequenceMatcher ratio on raw source code
- **Average similarity**: Weighted combination used for grouping

---

## Why Duplicates Appear

X-Ray groups functions by **structural** (AST hash) and **semantic** (token/ngram similarity)
similarity. Common sources:

| Type | Why | How to reduce |
|------|-----|----------------|
| **Exact/structural** | Same test names or near-identical fixtures across test files | Use shared `conftest` factories (e.g. `make_func`, `make_cls`) |
| **Command builders** | `_build_command` / `_build_format_cmd` in format, lint, security — each builds subprocess args | Extract shared `_build_tool_cmd(tool, base_args, exclude)` |
| **Tool → SmellIssue** | `_to_smell_issue` in lint and security — both map JSON to SmellIssue | Hard to unify (different tool output formats); accept or add a generic mapper |
| **Analyzer pattern** | `analyze`, `summary` across FormatAnalyzer, LintAnalyzer, SecurityAnalyzer | Inherit from `_AnalyzerBase`; keep overrides minimal |
| **LLM enrichment** | `enrich_with_llm` in smells vs duplicates — same prompt/response flow | Extract shared `_enrich_with_llm(entities, prompt_fn, attr_name)` |
| **main()** | Entry points in x_ray_claude, x_ray_exe, x_ray_ui, etc. | Acceptable — each is a different CLI; low priority |
| **Test setup** | Similar `def test_*` patterns (arrange/act/assert) | Use parametrize or shared helpers; some duplication is normal in tests |

---

## Programmatic Use

```python
from x_ray_claude import (
    scan_codebase,
    CodeSmellDetector,
    DuplicateFinder,
    LibraryAdvisor,
    SmartGraph,
    build_json_report,
)
from pathlib import Path

root = Path("./my_project")
functions, classes, errors = scan_codebase(root)

# Detect smells
detector = CodeSmellDetector()
smells = detector.detect(functions, classes)
summary = detector.summary()

# Find duplicates
finder = DuplicateFinder()
duplicates = finder.find(functions)

# Get library suggestions
advisor = LibraryAdvisor()
suggestions = advisor.analyze(duplicates, functions)

# Build report
report = build_json_report(root, functions, classes, smells, duplicates, suggestions, 0.0)
```

---

## Tips

See [README.md](../README.md) for architecture, grading formula, and Rustification.

1. **Start with `--smell`** to get a quick health check
2. **Use `--full-scan --graph`** for the most comprehensive view
3. **Exclude test directories** if you want to focus on production code:
   ```bash
   python x_ray_claude.py --full-scan --exclude tests --exclude Tests
   ```
4. **Use `--report`** to track code quality over time
5. **The graph HTML** works standalone — share it with your team
