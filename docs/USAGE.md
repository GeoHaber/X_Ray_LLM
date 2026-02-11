# X-Ray Claude — Usage Guide

## Installation

No installation required. X-Ray Claude is a single Python file with no external
dependencies (Python 3.10+ stdlib only).

```bash
# Just copy and run
python x_ray_claude.py --help
```

For testing, install pytest:
```bash
pip install pytest
```

---

## Command-Line Options

| Flag | Description |
|---|---|
| `--path PATH` | Root directory to scan (default: current directory) |
| `--smell` | Run code smell detection |
| `--duplicates` | Find cross-file function duplicates |
| `--suggest-library` | Suggest library extractions from duplicate groups |
| `--full-scan` | Run all features (smell + duplicates + library) |
| `--graph` | Generate interactive HTML graph |
| `--report FILE` | Save full JSON report to FILE |
| `--use-llm` | Enable LLM enrichment (requires Local LLM backend) |
| `--exclude DIR` | Directories to exclude (repeatable) |
| `--include DIR` | Only scan these directories (repeatable) |
| `--top N` | Show top N results per category (default: 20) |
| `-q, --quiet` | Minimal output |
| `-v, --verbose` | Verbose output |

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
- **Exact** — identical code (same MD5 hash)
- **Near** — structurally similar (cosine > 0.7 AND SequenceMatcher > 0.6)
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

Generates an interactive HTML file (`smart_analysis_graph.html`) with three tabs:
- **Graph** — D3.js force-directed graph with health-colored nodes
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
| `long-function` | Function exceeds line limit | > 80 lines |
| `god-class` | Class with too many methods | > 15 methods |
| `deep-nesting` | Excessive nesting depth | > 4 levels |
| `high-complexity` | High cyclomatic complexity | > 12 |
| `too-many-params` | Too many function parameters | > 6 params |
| `missing-docstring` | Public function without docstring | — |
| `dead-code` | Unreachable or unused code | — |
| `magic-numbers` | Hard-coded numeric literals | — |
| `feature-envy` | Function uses other module's data excessively | — |
| `duplicate-code` | Nearly identical code blocks | > 0.85 similarity |
| `long-parameter-list` | Excessive parameter count | > 8 params |
| `data-class-smell` | Class that's just data with no behavior | — |

### Similarity Scores

- **Token cosine** (0.0–1.0): Measures vocabulary overlap using TF-IDF vectors
- **Code similarity** (0.0–1.0): SequenceMatcher ratio on raw source code
- **Average similarity**: Weighted combination used for grouping

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
detector = CodeSmellDetector(functions, classes, root)
smells = detector.detect_all()

# Find duplicates
finder = DuplicateFinder(functions, root)
duplicates = finder.find_all()

# Get library suggestions
advisor = LibraryAdvisor(duplicates, root)
suggestions = advisor.suggest()

# Build report
report = build_json_report(root, functions, classes, smells, duplicates, suggestions)
```

---

## Tips

1. **Start with `--smell`** to get a quick health check
2. **Use `--full-scan --graph`** for the most comprehensive view
3. **Exclude test directories** if you want to focus on production code:
   ```bash
   python x_ray_claude.py --full-scan --exclude tests --exclude Tests
   ```
4. **Use `--report`** to track code quality over time
5. **The graph HTML** works standalone — share it with your team
