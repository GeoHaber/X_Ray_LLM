# X-Ray Claude — Smart AI-Powered Code Analyzer

**Version:** 4.0.0  
**License:** MIT  
**Python:** 3.10+

---

## What Is X-Ray Claude?

X-Ray Claude is a **smart, self-contained Python code analyzer** that combines
AST-based heuristics with optional Local LLM enrichment to deliver deep
insights into any Python codebase:

| Feature | Description |
|---|---|
| **Code Smell Detection** | 12+ categories — long functions, god classes, deep nesting, dead code, magic numbers, feature envy, and more |
| **Duplicate Finder** | 3-stage pipeline: hash match → TF-IDF cosine + SequenceMatcher → optional LLM confirmation |
| **Library Advisor** | Groups duplicate clusters and suggests shared library extractions with unified APIs |
| **Smart Graph** | Interactive HTML visualization with health-colored nodes, import edges, and 3 tabbed panels (Graph, Duplicates, Smells) |
| **Full JSON Reports** | Machine-readable output for CI/CD integration |

### Key Design Principles

- **Zero external dependencies** — works with only Python stdlib
- **LLM enrichment is optional** — all features provide useful results without any LLM
- **Fast parallel scanning** — uses `concurrent.futures` for multi-file processing
- **Unicode-safe output** — graceful fallback for terminals that don't support emoji
- **Single-file deployment** — one `.py` file, copy anywhere and run

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/your-username/X_Ray.git
cd X_Ray

# Basic scan (smells + structure)
python x_ray_claude.py --path /your/project

# Full analysis
python x_ray_claude.py --full-scan --path /your/project

# Generate interactive graph
python x_ray_claude.py --full-scan --graph --path /your/project

# Save JSON report
python x_ray_claude.py --full-scan --report results.json --path /your/project
```

## How It Works

See [docs/USAGE.md](docs/USAGE.md) for detailed usage instructions.  
See [docs/FUTURE_PLAN.md](docs/FUTURE_PLAN.md) for the roadmap.

---

## Running Tests

```bash
# Install test dependencies
pip install pytest

# Run the full test suite (113 tests)
python -m pytest tests/ -v
```

---

## Project Structure

```
X_Ray/
├── x_ray_claude.py          # The analyzer (single-file, self-contained)
├── README.md                 # This file
├── requirements.txt          # Dependencies (pytest for testing only)
├── docs/
│   ├── USAGE.md              # Detailed usage guide
│   └── FUTURE_PLAN.md        # Roadmap and future features
└── tests/
    └── test_xray_claude.py   # 113 comprehensive tests
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  CLI / main()                           │
│  --smell  --duplicates  --suggest-library  --full-scan  │
└───────────┬──────────┬─────────────┬────────────────────┘
            │          │             │
    ┌───────▼───┐ ┌────▼─────┐ ┌────▼──────────┐
    │ CodeSmell │ │Duplicate │ │  Library      │
    │ Detector  │ │ Finder   │ │  Advisor      │
    └───────┬───┘ └────┬─────┘ └────┬──────────┘
            │          │             │
    ┌───────▼──────────▼─────────────▼──────────┐
    │         scan_codebase() — AST Engine       │
    │  ThreadPoolExecutor + ast.parse per file   │
    └───────────────────┬────────────────────────┘
                        │
              ┌─────────▼─────────┐
              │   SmartGraph      │
              │  (HTML + D3.js)   │
              └───────────────────┘
```

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run the test suite: `python -m pytest tests/ -v`
4. Submit a pull request

---

*Built with AST heuristics + AI enhancement. Works on any Python codebase.*
