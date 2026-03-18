# Session Notes Backup — March 18, 2026

Source: conversation session memory (/memories/session/portability-audit-progress.md)

## Portability Audit Progress — March 18, 2026

### Status
- 16/16 PASS
- 0 HIGH
- 59 LOW remaining

### Completed Work

#### Hardcoded Paths (ALL FIXED)
Every C:\AI, C:\Users\Yo930, C:\Users\Geo, C:\Users\dvdze path replaced across all 16 projects.

#### requirements.txt Critical Fixes
- Add_Language: resolved git merge conflict
- Local_LLM: removed quotes from uvicorn line
- ZEN_AI_RAG: fixed pytest_asyncio name+version, removed duplicate PyPDF2
- X_Ray: commented x_ray_core (private local package)
- Normalized underscore to hyphen: huggingface-hub, psycopg-pool, edge-tts
- Added real missing deps to: Add_Language, Keep_1080p_or_BEST, LLM_TEST_BED, Swarm, X_Ray, X_Ray_LLM, ZenAIos-Dashboard, MARKET_AI

#### New X_Ray_LLM Portability Tool
- xray/rules/portability.py — PORT-001 to PORT-004
- xray/portability_audit.py — deep audit with CLI

### Remaining Work

#### 1) Missing dep false positives (59 LOW)
Most are local modules/stale imports, not real pip packages.
- Local project modules: Core, UI, controllers, adapters, decorators, etc.
- Stale/orphan imports: base_agent, connection_pool, trust_verify_supervisor
- Optional/conditional: TTS, piper, exllamav2, mlx_lm, mlx_vlm
- Sibling project refs: Local_LLM, local_llm, Video_Transcode→local_llm
- Real missing (LOW priority): duckduckgo_search, googlesearch, pystray, telethon in ZEN_RAG

#### 2) Audit filter improvements needed
- Better conditional import detection (try/except ImportError blocks)
- Consider marking project's own name as local (Local_LLM→Local_LLM)
- Some vlc and TTS imports are optional auto-installed

#### 3) --fix mode not implemented
portability_audit.py has --fix CLI flag but no auto-fix logic yet.
