# ENHANCE_PLAN.md — X-Ray LLM 18-Month Roadmap (2026-2027)

## Executive Vision

Transform X-Ray from a **powerful local tool** into a **distributed developer ecosystem** for code quality & security. Three pillars:

1. **Local-first agent** — Fastest, most autonomous scanning (remain < 5s for 50 files)
2. **IDE integration** — Shift-left security (real-time feedback while coding)
3. **Community marketplace** — Share rules, fixers, analyzers (leverage collective intelligence)

**2026 goals:** 2000+ GitHub stars, 10k+ monthly users, 100+ community contributions  
**2027 goals:** Mainstream adoption in Python ecosystem, de-facto SAST standard for small/medium teams

---

## PHASE 1: Q2 2026 (April-June) — Shift-Left Integration

### Theme: "Catch Issues Before Commit"

#### 1.1 Pre-Commit Hook (`xray/pre_commit_hook.py`)

**Goal:** Flag issues before developers commit broken code

**Deliverable:**
```yaml
# .pre-commit-config.yaml (developer adds this)
repos:
  - repo: https://github.com/username/X_Ray_LLM
    rev: v0.3.1
    hooks:
      - id: xray-security
        name: X-Ray Security Scan
        entry: xray pre-commit --severity HIGH
        language: python
        types: [python]
        stages: [commit]
```

**Features:**
- ✅ Scan only changed files (fast, < 1 sec)
- ✅ Block HIGH/MEDIUM by default (allow override with `--ignore`)
- ✅ Show fixer suggestions inline
- ✅ Integration with GitHub, GitLab desktop clients

**Effort:** 40 hours  
**Complexity:** Medium (subprocess handling, exit codes)  
**Owner:** Backend engineer

**Success metrics:**
- < 0.5 sec overhead on commit
- 80%+ of issues caught pre-commit
- 100+ pre-commit adopters by end of Q2

---

#### 1.2 GitHub Action: `xray-scan@v1`

**Goal:** Native CI/CD scanning in GitHub Actions

**Deliverable:** `.github/workflows/x_ray_scan.yml` template

```yaml
name: X-Ray Scan
on: [pull_request, push]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
      - uses: username/xray-scan@v1
        with:
          severity: HIGH
          export: sarif
      - uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: xray-results.sarif
```

**Features:**
- ✅ Comment on PR with findings
- ✅ Fail build if HIGH/MEDIUM found
- ✅ Export SARIF for GitHub Code Scanning
- ✅ Caching for fast re-runs

**Effort:** 30 hours  
**Complexity:** Medium (GitHub API integration, SARIF formatting)  
**Owner:** DevOps engineer

**Success metrics:**
- 500+ uses by end of Q2
- Compatible with GitHub Advanced Security
- <10 sec run time on typical repo

---

#### 1.3 Expand Rust Scanner: 15 Rules (from 3)

**Goal:** Parity with Python scanner for performance-critical teams

**Rules to add:**
- All 14 SEC rules (command injection, XSS, eval, SQL injection, etc.)
- 5 QUAL rules (bare except, hardcoded secrets, debug mode)
- Maintain 10× speed advantage over Python

**Effort:** 60 hours  
**Complexity:** High (tree-sitter + Rust AST parsing)  
**Owner:** Rust engineer (external hire or freelancer)

**Dependencies:**
- tree-sitter-python
- tree-sitter-javascript
- Pattern translation from Python to Rust

**Success metrics:**
- All 15 rules production-ready
- Regex parity with Python
- 500+ files/sec on large projects
- Zero regressions vs Python scanner

---

#### 1.4 Rule Governance Framework

**Goal:** Structured process for rule lifecycle management

**Deliverable:** `RULE_GOVERNANCE.md` + automation

```python
# Example rule definition (new format)
SEC_003_V2 = {
    "id": "SEC-003",
    "version": 2,  # NEW: version tracking
    "name": "Command injection via shell=True",
    "pattern": r"subprocess\.(run|Popen|call|check_.*)\(.+shell\s*=\s*True",
    "severity": "HIGH",
    "introduced_in": "v0.1.0",
    "updated_in": "v0.3.1",  # NEW: track updates
    "deprecation": None,  # NEW: for sunset
    "cwe": "CWE-78",  # NEW: CWE mapping
    "test_sample": "subprocess.run('ls', shell=True)",
}
```

**Process:**
1. **Proposed** — Issue with Label:rule-proposal
2. **Design review** — FalsePositive analysis, regression tests
3. **Implementation** — Add regex, sample code, tests
4. **Verification** — FP rate < 5% on corpus scan
5. **Published** — Announce in release notes, update guide
6. **Deprecated** (optional) — Shadow it out gracefully

**Effort:** 20 hours  
**Complexity:** Low (documentation + automation)  
**Owner:** Tech lead

**Success metrics:**
- 100% of rules versioned
- Clear deprecation timeline
- Community can propose rules via issue template

---

### Q2 Deliverables Summary

| Deliverable | Status | Users | ROI |
|-------------|--------|-------|-----|
| Pre-commit hook | ✅ | 100+ | $50k |
| GitHub Action | ✅ | 500+ | $200k |
| Rust 15-rule scanner | ✅ | 50+ | $100k |
| Rule governance | ✅ | N/A | --governance |
| **Q2 benefit** | | **650+ new users** | **$350k** |

---

## PHASE 2: Q3 2026 (July-September) — IDE Integration & ML

### Theme: "Real-Time Feedback in Your Editor"

#### 2.1 VSCode Extension (`xray-vscode`)

**Goal:** Real-time scanning while coding

**Features:**
- ✅ Scan on save (file save → findings in margin)
- ✅ Hover tooltip (show rule, severity, fix)
- ✅ "Quick fix" button (apply fixer inline)
- ✅ Settings panel (severity, excludes, fixers)
- ✅ Status bar indication (# findings)

**Deliverable:**
- `xray-vscode/` folder with TypeScript + VS Code API
- Publish to VS Code Marketplace
- ~500 LOC for basic MVP

**Effort:** 50 hours  
**Complexity:** High (VS Code API, IPC with Python)  
**Owner:** Frontend engineer or external hire

**Dependencies:**
- Python language server design
- JSON-RPC communication
- VS Code Marketplace account

**Success metrics:**
- 100+ installs by end of Q3
- < 500ms scan latency per file
- 4.0+ rating on marketplace
- Support Python 3.10-3.13

---

#### 2.2 ML-Based False Positive Suppression

**Goal:** Reduce false positives by 20-30% using ML

**Approach:**
1. **Data collection** — Gather 10k+ scan results (past 6 months)
2. **Annotation** — Community + maintainers label true/false positive
3. **Training** — Binary classifier on finding features:
   - rule_id, severity
   - File type, function/class context
   - Pattern match confidence
   - Comment/docstring proximity
4. **Deployment** — Classifier in scan pipeline (optional, can disable)

**Deliverable:**
- `xray/ml_false_positive_filter.py`
- ONNX model file (50 KB)
- Documentation (trade-offs, tuning)

**Effort:** 40 hours  
**Complexity:** High (ML engineering, data engineering)  
**Owner:** ML engineer (external hire)

**Success metrics:**
- FP rate: 8% → 5%
- Recall maintained: >95%
- <10ms latency per finding
- User can disable with `--no-ml-filter`

---

#### 2.3 Extended Rule Marketplace

**Goal:** Enable community to publish/subscribe custom rules

**Deliverable:**
- GitHub repo: `X-Ray-Rules-Registry`
- CLI support: `xray add-rule <github-url>`
- Web UI: Browse marketplace in X-Ray UI

**Marketplace structure:**
```
rules/
  ├── security/
  │   ├── CUST-001-sql-validator.py  # Community rule
  │   └── CUST-002-api-ratelimit.py
  └── quality/
      └── CUST-003-docstring-check.py
```

**Features:**
- ✅ Submit rule via PR to registry
- ✅ Semantic validation (does it compile?)
- ✅ FP testing (run on sample code)
- ✅ Ratings (community stars rule)
- ✅ Version tracking (SemVer for rules)

**Effort:** 50 hours  
**Complexity:** High (registry design, CI validation)  
**Owner:** Backend engineer

**Success metrics:**
- 20+ community rules by end of Q3
- 80% adoption rate of featured rules
- Zero malicious rules (reputation system)

---

#### 2.4 Datadog AI Integration (Pilot)

**Goal:** Explore partnership with Datadog for AI rule suggestions

**Approach:**
- Datadog scans code → detects patterns
- Suggests "add to X-Ray rules" for team-specific issues
- X-Ray validates, stores as private rule

**Effort:** 20 hours (exploratory)  
**Complexity:** Medium (vendor API integration)  
**Owner:** Tech lead (external Datadog contact)

**Success metrics:**
- Proof of concept working
- 5-10 new team-specific rules validated
- Path for production integration

---

### Q3 Deliverables Summary

| Deliverable | Status | Users | ROI |
|-------------|--------|-------|-----|
| VSCode extension | ✅ | 100+ | $150k |
| ML FP suppression | ✅ | All | $100k |
| Rule marketplace | ✅ | 20+rule authors | $50k |
| Datadog pilot | ✅ | -- | Exploration |
| **Q3 benefit** | | **100+ new IDE users** | **$300k** |

---

## PHASE 3: Q4 2026 (October-December) — Automated Rule Mining & Scaling

### Theme: "Knowledge at Scale"

#### 3.1 Automated Rule Mining from OWASP/CWE

**Goal:** Use LLM to generate new rules from vulnerability databases

**Approach:**
1. **Scrape** OWASP Top 10 + CWE Top 25 descriptions
2. **Prompt Claude** "Extract vulnerable code pattern from: [CVE description]"
3. **Codify** LLM output into regex + sample code
4. **Validate** Run on corpus, measure FP rate
5. **Publish** Add to rules database if confident

**Expected output:** 10-20 new rules/year

**Deliverable:**
- `xray/rule_mining.py` (LLM-powered rule generator)
- `scripts/mine_rules.py` (automation)
- 10+ new rules in Q4 2026

**Effort:** 60 hours  
**Complexity:** High (LLM integration, validation)  
**Owner:** ML engineer

**Success metrics:**
- 10+ new rules published
- FP rate < 5% on all new rules
- Community feedback incorporated

---

#### 3.2 JetBrains Plugin (IntelliJ/PyCharm)

**Goal:** Bring X-Ray to JetBrains IDE ecosystem

**Deliverable:**
- `xray-jetbrains/` plugin (Kotlin)
- Publish to JetBrains Marketplace
- Feature parity with VSCode extension

**Effort:** 60 hours  
**Complexity:** High (JetBrains API, plugin architecture)  
**Owner:** Frontend engineer (external hire)

**Success metrics:**
- 100+ installs by end of Q4
- 4.0+ rating on marketplace
- Real-time scanning working

---

#### 3.3 Semantic Taint Tracking (Research)

**Goal:** Implement Semgrep-style taint tracking for data flow analysis

**Example:** Track variable assignment through function calls
```python
user_input = request.args.get('id')  # Source
query = f"SELECT * FROM users WHERE id={user_input}"  # Sink (SQL injection)
execute(query)  # Vulnerable
```

**Approach:**
- Build on existing `graph.py` (call graph analysis)
- Trace variable assignments + function returns
- Flag when tainted variable reaches sensitive sink

**Effort:** 80 hours (research + prototype)  
**Complexity:** Very high (SSA, data flow graphs)  
**Owner:** Research engineer (external hire) or Q1 2027

**Success criteria:**
- Prototype catching 5-10 real vulnerabilities
- Decision on production viability by end of Q4

---

#### 3.4 "SOTA Rule" Monthly Community Poll

**Goal:** Engage community in rule prioritization

**Mechanism:**
- Monthly poll: "What vulnerability should we scan for next?"
- Top vote → Mining team adds it next month
- Community votes on new rules via GitHub issues

**Effort:** 5 hours/month  
**Complexity:** Low (GitHub issues + automation)  
**Owner:** Community manager (part-time)

**Success metrics:**
- 100+ votes/month
- 12 community-suggested rules added in 2026

---

### Q4 Deliverables Summary

| Deliverable | Status | Users | ROI |
|-------------|--------|-------|-----|
| Rule mining from CVEs | ✅ | All | $200k |
| JetBrains plugin | ✅ | 100+ | $150k |
| Taint tracking research | ✅ | -- | Preliminary |
| Community polls | ✅ | 100+voters | --engagement |
| **Q4 benefit** | | **100+ new IDE users** | **$350k** |

---

## PHASE 4: 2027 (Months 13-18) — Ecosystem & Production Hardening

### Theme: "Enterprise-Ready Security Platform"

#### 4.1 JetBrains Plugin (Production)

Moving taint tracking research to production if promising. Otherwise, maintain IDE plugin ecosystem.

#### 4.2 Go Language Support (10 Rules)

**Goal:** Expand beyond Python to Go (common in startups, microservices)

**Rules to add:**
- SEC-001: SQL injection
- SEC-003: Command injection
- SEC-009: Insecure deserialization
- QUAL-001: Bare error handling
- Others: Similar to Python

**Effort:** 50 hours  
**Complexity:** Medium (tree-sitter-go)  
**Owner:** Rust engineer

**Dependencies:**
- tree-sitter-go, tree-sitter-gomod
- Pattern translation from Python to Go

**Success metrics:**
- 10 rules production-ready
- 10k+ scan runs on Go repos

---

#### 4.3 Rule Marketplace Goes Public

**Goal:** Publish curated list of 50+ community rules

**Deliverable:**
- `rules/marketplace.json` (registry)
- Web UI: Browse, install, rate
- CLI: `xray install rulespack <name>`

**Featured rulesets:**
- "OWASP Top 10" (official)
- "Team-Specific SMB Rules" (community)
- "Fintech Security Rules" (curated)
- "Startup Compliance" (SOC 2 focused)

**Effort:** 40 hours  
**Complexity:** Medium (UX, registry design)  
**Owner:** Frontend engineer

**Success metrics:**
- 50+ published rulesets
- 1000+ rulesets installed
- 4.0+ avg rating

---

#### 4.4 Formal Performance Budget Enforcement

**Goal:** Lock in performance SLAs in CI/CD

**Mechanism:**
- Benchmark: 50 files → < 5 sec
- Benchmark: 1000 files → < 30 sec
- Benchmark: 10000 files → < 3 min
- CI fails if any benchmark regression > 10%

**Deliverable:**
- `pytest --performance-budget 5s` plugin
- `.xray_benchmarks.json` (baseline)
- GitHub Action: performance-check@v1

**Effort:** 30 hours  
**Complexity:** Medium (pytest plugin, monitoring)  
**Owner:** DevOps engineer

**Success metrics:**
- All benchmarks met in all releases
- Zero performance regressions
- Community confidence in speed

---

#### 4.5 Security Audit & Pen Test

**Goal:** Professional security validation

**Deliverable:**
- Full pen test report (find vulnerabilities in X-Ray itself)
- Remediation plan + fixes
- Security badge (e.g., "Security audit passed 2026")

**Effort:** 80 hours (external vendor)  
**Complexity:** External (3rd-party firm)  
**Cost:** $5k-$15k (vendor fees)  
**Owner:** Tech lead (coordinate with vendor)

**Success metrics:**
- Zero critical/high findings
- Medium/low findings remediated
- Public trust (security badge)

---

#### 4.6 LLM Rule Improvement

**Goal:** Use LLM to improve existing rules (reduce FPs, improve matches)

**Approach:**
- Feed LLM: "Rule PY-001: [description], FP cases: […]"
- LLM: "Replace regex with better version"
- Validate → publish

**Effort:** 40 hours  
**Complexity:** Medium (LLM prompting, testing)  
**Owner:** ML engineer

**Success metrics:**
- 5-10 rules improved
- FP rate < 3% (vs 5%)

---

### 2027 Deliverables Summary

| Deliverable | Status | Users | Timeline |
|-------------|--------|-------|----------|
| JetBrains production | ✅ | 200+ | Q1 2027 |
| Go language support | ✅ | 100+ Go teams | Q2 2027 |
| Rule marketplace public | ✅ | 1000+ users | Q2 2027 |
| Performance budgeting | ✅ | All devops | Q3 2027 |
| Security audit | ✅ | -- | Q3 2027 |
| LLM rule improvement | ✅ | All users | Q4 2027 |
| **2027 benefit** | | **500+ new users** | **$1M+** |

---

## RESOURCE PLAN

### Hiring (2026)

| Role | Count | Start | Cost/Year |
|------|-------|-------|-----------|
| Rust engineer (contractor) | 1 | Q2 | $60k |
| Frontend engineer (contractor) | 1 | Q2 | $80k |
| ML engineer (contractor) | 1 | Q3 | $100k |
| Community manager (part-time) | 1 | Q3 | $30k |
| **Total 2026 hiring** | | | **$270k** |

### Budget Allocation (2026)

| Area | Budget |
|------|--------|
| Engineering (salaries + infra) | $150k |
| Contractor/services | $80k |
| Marketing + events | $20k |
| Infrastructure + tools | $10k |
| **Total 2026 budget** | **$260k** |

### Funding Strategies

1. **OSS grants** — Apply for GitHub Sponsors, Open Source Collective grants
2. **Sponsorships** — Companies wanting to fund features (VSCode, Datadog)
3. **Crowdfunding** — If needed (unlikely, given ROI)
4. **Team allocation** — 50% of team time budgeted for X-Ray

---

## SUCCESS METRICS (18-Month Targets)

### Adoption

| Metric | Target (2027) | Current (2026) |
|--------|-------------|----------------|
| GitHub stars | 2000+ | ~150 |
| PyPI monthly downloads | 5000+ | ~200 |
| VSCode extension installs | 500+ | 0 |
| JetBrains plugin installs | 300+ | 0 |
| Pre-commit users | 1000+ | 0 |
| Community rules published | 50+ | 0 |

### Quality

| Metric | Target | Current |
|--------|--------|---------|
| False-positive rate | < 3% | ~8% |
| Fixer reliability | > 95% | 100% (7 rules) |
| Test coverage | > 90% | ~85% |
| Rule count | 50+ | 42 |
| Language support | 3 languages | Python/JS |

### Business

| Metric | Target | Current |
|--------|--------|---------|
| Annual benefit (saved by users) | $50M+ | --measured |
| Community contributors | 50+ | 0 |
| Enterprise customers | 10+ | 0 |
| Partnerships | 5+ | 0 |

---

## RISK MITIGATION

| Risk | Probability | Mitigation |
|------|----------|-----------|
| **Competing tool dominates** | Low | Focus unique features (agent loop + fixers) |
| **Community adoption stalls** | Medium | Invest in marketing, partnerships |
| **Scope creep (too many features)** | High | Strict prioritization, quarterly re-planning |
| **Maintainer burnout** | Medium | Distribute responsibility, hire early |
| **Technical debt accumulates** | Medium | 20% sprint time for refactor |

---

## DECISION GATES

### Q2 2026 Gate: Pre-Commit + GitHub Action Go-Live

**Criteria:**
- [ ] Pre-commit hook < 1 sec overhead
- [ ] GitHub Action < 10 sec run time
- [ ] Rust scanner 15 rules production-ready
- [ ] 500+ users on GitHub Action

**Decision:** Proceed to Q3 (IDE integration) or pivot?

### Q3 2026 Gate: IDE Integration Launch

**Criteria:**
- [ ] VSCode extension 100+ installs, 4.0+ rating
- [ ] ML FP suppression working (5% FP rate)
- [ ] Rule marketplace 20+ rules

**Decision:** Proceed to Q4 (taint tracking research) or delay?

### Q4 2026 Gate: Taint Tracking Viability

**Criteria:**
- [ ] Taint tracking prototype catches 10+ real vulns
- [ ] Regression tests passing
- [ ] < 500ms latency

**Decision:** Full 2027 prodution investment or deprioritize?

---

## COMMUNICATION PLAN

### Monthly
- Internal standup (team progress)
- Changelog (users, community)
- GitHub releases (features, fixes)

### Quarterly
- Blog post (major feature announcement)
- Developer metrics update (stars, downloads)
- Quarterly retrospective (roadmap adjustment)

### Annually
- Community keynote (conference talk or webinar)
- Annual report (impact, metrics, plans)
- Roadmap refresh (2027-2028 plans)

---

## CONCLUSION

**X-Ray LLM's 18-month vision:**
- From *local tool* → **distributed ecosystem**
- From *42 rules* → **50+ built-in + 50+ community rules**
- From *CLI only* → **IDE + pre-commit + GitHub Actions**
- From *no ML* → **ML-enhanced (FP suppression, rule mining)**
- From *Python only* → **Go support, Rust performance parity**

**Expected impact:**
- 2000+ stars (mainstream recognition)
- 5000+ monthly users
- $50M+ annual benefit across all users
- 10+ enterprise customers
- 50+ community contributors

**Key success factor:** **Community > Features**. Build a thriving community of rule authors, maintainers, and users. They will drive innovation faster than the core team.

---

**Roadmap owner:** Tech Lead  
**Last updated:** 2026-03-21  
**Review cycle:** Quarterly (gate decisions every 3 months)  
**Next review:** 2026-06-30 (Q2 gate decision)
