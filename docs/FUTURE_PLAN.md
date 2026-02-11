# X-Ray Claude — Future Plan & Roadmap

## Current Version: 4.0.0

### What's Implemented

- [x] AST-based code scanning with parallel execution
- [x] 12+ code smell categories with severity levels
- [x] 3-stage duplicate detection (hash → cosine+SequenceMatcher → LLM)
- [x] Library extraction advisor
- [x] Interactive HTML graph with 3 tabbed panels
- [x] Full JSON reporting
- [x] Unicode-safe terminal output
- [x] Optional LLM enrichment
- [x] 113 comprehensive tests

---

## Roadmap

### v4.1 — Enhanced Detection (Next)

- [ ] **Type annotation coverage** — detect files/functions with low type hint coverage
- [ ] **Import cycle detection** — find circular imports across the project
- [ ] **Unused import detection** — flag imports that are never referenced
- [ ] **Test coverage correlation** — correlate smells with test coverage data
- [ ] **Configurable thresholds** — YAML/TOML config file for smell thresholds

### v4.2 — Multi-Language Support

- [ ] **JavaScript/TypeScript** — extend AST parsing to JS/TS via tree-sitter
- [ ] **Rust** — parse `.rs` files for cross-language duplicate detection
- [ ] **Language-agnostic tokenizer** — unified token pipeline across languages

### v4.3 — CI/CD Integration

- [ ] **GitHub Actions integration** — pre-built action for quality gates
- [ ] **Trend tracking** — compare reports across commits, show quality delta
- [ ] **PR comments** — automatically post findings on pull requests
- [ ] **Badge generation** — code health badges for README
- [ ] **Exit code support** — non-zero exit on critical smell count

### v4.4 — Advanced AI Features

- [ ] **Auto-refactoring suggestions** — generate actual refactored code
- [ ] **Design pattern detection** — identify common patterns and anti-patterns
- [ ] **Dependency analysis** — deep package dependency graph
- [ ] **Security smell detection** — hardcoded secrets, unsafe eval, SQL injection patterns
- [ ] **Multi-model support** — use different LLMs for different analysis tasks

### v5.0 — Platform

- [ ] **Web dashboard** — persistent web UI for browsing analysis results
- [ ] **Project history** — track code health over time with charts
- [ ] **Team features** — shared rules, team-specific thresholds
- [ ] **Plugin system** — custom smell detectors as plugins
- [ ] **IDE integration** — VS Code extension for inline smell highlighting

---

## Contributing Ideas

Have a feature idea? Open an issue on GitHub with:
1. **What** the feature does
2. **Why** it's useful
3. **How** it could work (rough approach)

---

## Design Philosophy

1. **Zero dependencies first** — core features work with stdlib only
2. **Fast by default** — heuristics first, LLM only for enrichment
3. **Single-file deployable** — copy one `.py` file and run anywhere
4. **Test everything** — maintain >95% test coverage
5. **Graceful degradation** — works on any terminal, any OS
