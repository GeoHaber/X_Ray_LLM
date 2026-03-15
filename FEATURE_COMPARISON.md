# X-Ray LLM — Feature Comparison & Competitive Analysis

## Updated after Phase 1-4 Implementation

---

## Tool Overview

| Tool | Type | Pricing | Languages | Focus |
|------|------|---------|-----------|-------|
| **X-Ray LLM** | Local scanner + Web UI | Free/Open Source | Python (+ JS/TS/Web) | Full-stack code quality |
| **CodeRabbit** | AI PR review (SaaS) | Free tier → $19/seat/mo | 40+ languages | PR-level code review |
| **SonarQube** | Platform (Server/Cloud) | Free Community → $$$$ | 30+ languages | Enterprise code quality |
| **Bandit** | CLI scanner | Free/Open Source | Python only | Security only |
| **Ruff** | CLI linter/formatter | Free/Open Source | Python only | Lint + format |
| **Semgrep** | CLI/SaaS | Free → $$ | 30+ languages | SAST / custom rules |
| **Vulture** | CLI | Free/Open Source | Python only | Dead code only |
| **Prospector** | CLI (meta-linter) | Free/Open Source | Python only | Aggregation |

---

## Feature Matrix

### Legend
- ✅ = Full support
- ⚡ = Partial / basic support
- ❌ = Not available
- 🔌 = Via plugin/integration

| Feature | X-Ray LLM | CodeRabbit | SonarQube | Bandit | Ruff | Semgrep | Vulture |
|---------|-----------|------------|-----------|--------|------|---------|---------|
| **Core Analysis** | | | | | | | |
| Regex pattern rules | ✅ 28 rules | ❌ | ✅ 5000+ | ❌ | ✅ 800+ | ✅ 2000+ | ❌ |
| Security scanning | ✅ 10 rules + Bandit | ✅ AI-based | ✅ | ✅ | ⚡ | ✅ | ❌ |
| Code quality rules | ✅ 10 rules | ✅ AI-based | ✅ | ❌ | ✅ | ✅ | ❌ |
| Python-specific rules | ✅ 8 rules | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Phase 1: Quick Wins** | | | | | | | |
| Dark/Light theme toggle | ✅ | N/A (web) | ✅ | N/A | N/A | N/A | N/A |
| Format checking | ✅ ruff format | ❌ | ⚡ | ❌ | ✅ | ❌ | ❌ |
| Project health check | ✅ 10 checks | ❌ | ⚡ | ❌ | ❌ | ❌ | ❌ |
| Severity filtering | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Remediation time est. | ✅ per-finding | ⚡ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Phase 2: Core Parity** | | | | | | | |
| Bandit integration | ✅ + secrets | ❌ | 🔌 | ✅ native | ❌ | ❌ | ❌ |
| Secret detection | ✅ 7 patterns + entropy | ✅ AI | ✅ | ⚡ | ❌ | ✅ | ❌ |
| Dead function detection | ✅ cross-file | ⚡ AI | ✅ | ❌ | ❌ | ❌ | ✅ |
| Historical trend chart | ✅ canvas chart | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Before/After comparison | ✅ | ✅ (PR diff) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Inline code preview | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Phase 3: Advanced** | | | | | | | |
| AST code smell detect | ✅ 10 smell types | ✅ AI | ✅ | ❌ | ⚡ | ⚡ | ❌ |
| Duplicate detection | ✅ hash-based | ⚡ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Temporal coupling (git) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Dependency graph | ✅ vis-network | ✅ diagrams | ⚡ | ❌ | ❌ | ❌ | ❌ |
| Multi-dimension grading | ✅ 4 dimensions | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Quality gate | ✅ configurable | ⚡ custom checks | ✅ | ❌ | ❌ | ❌ | ❌ |
| Complexity treemap | ⚡ density chart | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Phase 4: Specialized** | | | | | | | |
| Pyright type checking | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Release readiness | ✅ 7 checks | ❌ | ⚡ | ❌ | ❌ | ❌ | ❌ |
| Test stub generation | ✅ pytest stubs | ✅ unit tests | ❌ | ❌ | ❌ | ❌ | ❌ |
| Coverage analysis | ✅ function-level | ⚡ | ✅ | ❌ | ❌ | ❌ | ❌ |
| AI code detection | ✅ heuristic | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Web smells (JS/TS/HTML) | ✅ 12 patterns | ✅ AI | ✅ | ❌ | ❌ | ✅ | ❌ |
| SATD debt scanner | ✅ 12 markers | ❌ | ⚡ | ❌ | ❌ | ❌ | ❌ |
| Git hotspot analysis | ✅ churn-based | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Engines & Performance** | | | | | | | |
| Python engine | ✅ | N/A | ✅ | ✅ | ✅ | ✅ | ✅ |
| Rust engine (fast) | ✅ cross-compiled | ❌ | ❌ | ❌ | ✅ (core) | ❌ | ❌ |
| Scan progress + abort | ✅ | N/A | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Auto-Fix** | | | | | | | |
| Auto-fix rules | ✅ 7 rules | ✅ AI 1-click | ✅ | ❌ | ✅ | ✅ | ❌ |
| Fix preview (diff) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Bulk fix | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ |
| **UI & Reporting** | | | | | | | |
| Web UI | ✅ standalone | ✅ SaaS | ✅ | ❌ | ❌ | ✅ cloud | ❌ |
| Export JSON | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Export HTML report | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Grade card (A-F) | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Directory browser | ✅ | N/A | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Integration** | | | | | | | |
| Runs locally (offline) | ✅ | ❌ | ✅ self-host | ✅ | ✅ | ✅ | ✅ |
| No account required | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| PR review (GitHub) | ❌ | ✅ | ✅ | 🔌 | 🔌 | ✅ | ❌ |
| IDE integration | ❌ | ✅ VS Code | ✅ | ❌ | ✅ | ✅ | ❌ |
| CI/CD pipeline | ⚡ quality gate JSON | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| LLM-powered analysis | ⚡ (optional) | ✅ core | ❌ | ❌ | ❌ | ⚡ pro | ❌ |

---

## CodeRabbit Deep Dive

**What CodeRabbit excels at (and X-Ray LLM doesn't):**
1. **AI-powered PR reviews** — context-aware line-by-line review on GitHub/GitLab PRs
2. **Multi-language support** — 40+ languages out of the box
3. **Learning from feedback** — remembers team preferences, improves over time
4. **40+ linter integrations** — aggregates ESLint, Ruff, golangci-lint, etc. in one review
5. **Issue planner** — turns Jira/Linear issues into implementation plans
6. **IDE + CLI** — VS Code extension and CLI tool for pre-commit reviews
7. **Architecture diagrams in PRs** — auto-generates change impact diagrams
8. **1-click fix commits** — applies fixes directly in the PR

**What X-Ray LLM has that CodeRabbit doesn't:**
1. **Local-only, offline** — no data leaves your machine, no account needed
2. **Dual Python + Rust engines** — cross-compiled scanner for ~10x speed
3. **AST-level analysis** — code smells, dead functions, complexity, nesting depth
4. **Quality grading (A-F)** with 4-dimension breakdown (security/reliability/style/overall)
5. **Quality gate** with configurable thresholds
6. **Historical trend chart** — track quality over time across sessions
7. **Temporal coupling analysis** from git history
8. **SATD technical debt scanner** (TODO/FIXME/HACK categorization + time estimates)
9. **Git hotspot analysis** (churn-based file risk ranking)
10. **Dependency graph visualization** (vis-network)
11. **Duplicate code detection** (hash-based)
12. **Release readiness assessment**
13. **AI code detection** (heuristic pattern matching)
14. **Test stub generation** (pytest stubs for untested functions)
15. **Pyright type checking integration**
16. **Interactive file browser** in the UI
17. **Free forever, open source** — CodeRabbit is $19/seat/month for Pro

---

## Competitive Positioning

### X-Ray LLM's Unique Value Proposition
- **All-in-one code quality dashboard** — 20+ analysis tools in a single UI
- **Zero-dependency on cloud** — works offline, no API keys, no accounts
- **Dual-engine scanning** — Python for flexibility, Rust for speed (~10x faster)
- **Production-quality web UI** — dark/light mode, interactive charts, export
- **Free and open source** — no per-seat pricing, no feature gates

### Where Each Tool Wins

| Scenario | Best Tool | Why |
|----------|-----------|-----|
| Quick local project audit | **X-Ray LLM** | All-in-one dashboard, 20+ tools, no setup |
| PR code review in team | **CodeRabbit** | AI-powered, learns from team, inline in PR |
| Enterprise compliance | **SonarQube** | 5000+ rules, quality profiles, branch analysis |
| Python security audit | **Bandit** + **X-Ray LLM** | Bandit integrated in X-Ray, combined coverage |
| Fast Python linting | **Ruff** (via X-Ray) | Ruff integrated in X-Ray, auto-fix included |
| Custom SAST rules | **Semgrep** | DSL for writing rules, large community |
| Finding dead code | **X-Ray LLM** | Cross-file AST analysis, Vulture-like + more |

---

## Feature Count Summary

| Tool | Analysis Features | UI Features | Total |
|------|------------------|-------------|-------|
| **X-Ray LLM** | 22 | 12 | **34** |
| **CodeRabbit** | 8 (AI-powered) | 6 | **14** |
| **SonarQube** | 15+ | 10+ | **25+** |
| **Bandit** | 1 | 0 | **1** |
| **Ruff** | 2 | 0 | **2** |
| **Semgrep** | 3 | 2 | **5** |
| **Vulture** | 1 | 0 | **1** |

### X-Ray LLM Analysis Features (22)
1. Pattern-based scanning (28 rules)
2. Bandit security integration
3. Secret/API key detection
4. Code smell detection (10 smell types)
5. Dead function detection
6. Duplicate code detection
7. Temporal coupling analysis
8. Project health check
9. Format checking (ruff)
10. SATD technical debt scanning
11. Git hotspot analysis
12. Import/dependency parsing
13. Ruff auto-fix integration
14. Pyright type checking
15. Release readiness assessment
16. AI code detection
17. Web smells (JS/TS/HTML/CSS)
18. Test stub generation
19. Coverage analysis
20. Quality gate evaluation
21. Multi-dimension grading
22. Remediation time estimation

### X-Ray LLM UI Features (12)
1. Dark/Light theme toggle
2. Interactive file browser
3. Quality grade card (A-F)
4. Before/After comparison
5. Historical trend chart
6. Density minimap
7. Dependency graph (vis-network)
8. Fix preview + apply
9. JSON/HTML/Gate export
10. Search/filter across all views
11. Scan progress + abort
12. 15+ tabbed views

---

*Generated: $(date), Post Phase 1-4 Implementation*
