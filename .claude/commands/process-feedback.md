# Process User Feedback

Takes user feedback (pasted or from a file) and processes it into the backlog. Valid for **X-Ray** (use docs/FUTURE_PLAN.md or docs/backlog.md) or for any Python project.

**Reference:** [Full-SDLC Multi-Agent Development with Claude Code](https://www.linkedin.com/pulse/from-idea-production-full-sdlc-multi-agent-claude-code-branzan-vmjdc/)

## PROCESS
1. Use the `feedback-triage` subagent to categorize and prioritize the feedback
2. For X-Ray: append/update docs/backlog.md or docs/FUTURE_PLAN.md
3. For any P0 bugs, immediately flag to user: "CRITICAL BUG FOUND: {description}"
4. Show summary: X bugs, Y feature requests, Z UX issues
5. Ask: "Want me to start fixing P0 bugs now?"

## If yes for P0 bugs:
1. Create a hotfix branch from main: `git checkout -b hotfix/{bug-id} main`
2. Use `backend-dev` or `frontend-dev` subagent to fix
3. Use `test-engineer` subagent to add regression test
4. Create PR directly to main (hotfix fast lane)

## For feature requests marked as "do next":
1. Run them back through the mini-pipeline:
   - `spec-writer` to add stories to docs/user-stories.md
   - `architect` to assess impact on architecture
   - `implementer` to build in a feature branch
   - `test-engineer` to add tests
   - `reviewer` to review
   - PR to develop → main

## CONSTRAINTS
- Ensure docs/backlog.md exists; create from feedback-triage output if missing
- Hotfixes: merge to main first, then cherry-pick or merge to develop
