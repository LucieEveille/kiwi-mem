# 🥝 kiwi-mem

**Most AI memory systems are databases. kiwi-mem is a brain.**

[中文版 →](README.md)

---

## What it does

kiwi-mem gives your AI long-term memory that works like a human brain.

Not "save chat logs and search them later" — actually human-like: things you don't mention gradually fade, things you talk about often stick harder, a night of sleep reorganizes scattered fragments into deeper understanding, last year's events compress into rough outlines while yesterday stays vivid.

All of these mechanisms work together as a unified filtering system: **your AI remembers what you'd remember, and forgets what neither of you would care about.** Without blowing up the context window or burning through your API budget.

Technically, it's a lightweight proxy gateway that sits between you and any LLM, compatible with any OpenAI-format client and provider. Docker one-click deploy, browser-based admin panel.

**Stack**: Python / FastAPI · PostgreSQL + pgvector · Docker · MIT License

![Feature overview](docs/feature-overview.png)

---

## How memory works like a brain

The core of kiwi-mem isn't any single feature — it's multiple mechanisms working in concert to make AI memory behave like human intuition:

### 🔥 Fades and strengthens

Every memory has a "heat" score. Time makes it naturally decay, but if you keep bringing up the same topic, it warms back up. High-emotion memories decay slower — just like how you remember moments that moved you. Heat determines how memories enter the conversation: hot memories get injected in full, warm ones as summaries, cold ones stay quiet.

### 🌙 Sleeps and wakes up smarter

Dream simulates how the human brain consolidates memories during sleep. It works in three layers: first cleans up outdated and duplicate fragments, then merges related fragments into coherent "memory scenes", and finally infers things you never explicitly said but your AI should understand. You can trigger it manually, or let the system decide when it's time to sleep.

### 📅 Recent is vivid, distant is hazy

The calendar system auto-compresses chat history into hierarchical summaries: day → week → month → quarter → year. When injecting into conversation, recent days get full detail, last week gets abbreviated, older periods get high-level overviews. Just like how you recall the past — you know what you ate yesterday, but last month is mostly outlines.

### 🧩 Contradictions update, important things stick

When a new memory conflicts with an old one (you changed jobs, moved cities), the system auto-invalidates the outdated version. Memories you've explicitly marked as important, or that keep getting recalled, get locked — they never decay and never auto-delete.

### ⚡ Budget and context aware

All static content (persona, profile, locked memories, calendar summaries) is ordered first in the prompt to hit cache, dynamic content (search results, drowsiness hints) comes after. This injection order can save up to 90% on API input costs. Combined with calendar compression and heat-tiered injection, even months of memories won't overflow your context window.

---

## Who is it for

kiwi-mem is designed to **remember a person** — your habits, preferences, emotions, experiences, growth. It's not an enterprise knowledge base, not a document retrieval system, not a knowledge graph.

It works best for:

🏠 **Life assistant** — Remembers your dietary habits, health conditions, schedule preferences. Gets better the longer you use it.

🩶 **Long-term companion** — Emotional support, daily conversation, deep relationships. Your AI actually "knows you" instead of starting fresh every time.

📖 **Creative partner** — Serialized fiction, worldbuilding, roleplay. All settings, plot threads, and character arcs stay in memory.

🎓 **Learning tutor** — Tracks your progress, weak spots, and past questions. Tutoring gets more targeted over time.

---

## Quick start

### Prerequisites

- Docker & Docker Compose (recommended — includes PostgreSQL + pgvector)
- An LLM API key (OpenRouter / OpenAI / DeepSeek / any OpenAI-compatible provider)

> 💡 No Docker? You can deploy manually with Python 3.12+ and your own PostgreSQL (pgvector extension required).

### Three steps

```bash
# 1. Clone
git clone https://github.com/LucieEveille/kiwi-mem.git
cd kiwi-mem

# 2. Configure
cp .env.example .env
# Edit .env with your API_KEY (other settings have defaults)

# 3. Launch
docker compose up -d
```

Visit `http://localhost:8080` — if you see `{"status":"running"}`, you're good.

### What's next

- Visit `/admin` for the browser-based admin panel
- Point your chat client's API endpoint to `http://localhost:8080/v1`
- Works with any OpenAI-format frontend: ChatBox, NextChat, SillyTavern, or your own

> 💡 80+ parameters can be changed at runtime via the admin panel — no restart needed.

---

## How it compares

<details>
<summary>Click to expand comparison table</summary>

| Capability | kiwi-mem | Typical RAG memory |
|---|---|---|
| Memory decay & heating | ✅ Heat system (time decay + recall frequency + emotional intensity) | ❌ Stored forever |
| Sleep consolidation | ✅ Dream (cleanup → consolidation → foresight) | ❌ None |
| Temporal compression | ✅ Day → week → month → quarter → year | ❌ Everything flat |
| Contradiction detection | ✅ Auto-invalidates outdated memories | ❌ None |
| Memory locking | ✅ Important memories never decay | ❌ None |
| User profile | ✅ Auto-updated daily, structured portrait | ❌ None |
| Prompt caching | ✅ Static-first injection, up to 90% input cost savings | ❌ None |
| Context control | ✅ Heat-tiered + calendar compression, no overflow | ❌ Easily exceeds limits |

</details>

---

## Full feature list

<details>
<summary>Click to expand</summary>

### 🧠 Memory extraction & retrieval
- **RRF hybrid search**: Vector + keyword search in parallel, Reciprocal Rank Fusion merge
- **Auto-extraction**: Every N turns, extracts key info as memory fragments
- **jieba Chinese segmentation**: Custom domain vocabulary
- **Synonym expansion**: "medication" finds "prescription", "drugs", "medicine"
- **Semantic deduplication**: Similar memories auto-detected

### 🔥 Memory heat system
- Time decay (half-life) · recall heating · query diversity · emotional weight
- Tiered injection (hot → full text / warm → summary / cold → skip)
- Frequently recalled memories auto-promote to permanent

### 🌙 Dream consolidation
- Cleanup layer (remove outdated / duplicate / contradictory fragments)
- Consolidation layer (fragments → MemScenes)
- Growth layer (Foresight — infer implications)
- Triggers: manual / drowsiness reminder / auto after 24h inactivity

### 📅 Calendar hierarchy
- Auto-generated day pages · day → week → month → quarter → year compression
- Matryoshka injection (recent = detailed, distant = summarized)
- User profile: four-section structure, updated daily

### ⚡ Smart system prompt injection
- Static zone (persona → profile → locked → calendar) hits cache
- Dynamic zone (search results → drowsiness hint) per-turn
- Auto-handoff context between chat windows
- Template variable support

### 🔌 Multi-provider LLM routing
- Multiple providers, auto-select by model name
- Balance queries, model grouping
- Any OpenAI-compatible API

### 🔧 Tools & extensions
- MCP Server (20+ tools) + MCP Client
- Web search (7 engines)
- Context compression, file parsing, chain-of-thought display

### 🛡️ Deployment & management
- Web admin panel · cloud sync · backup/restore
- Reminder system · admin auth · Docker deploy

</details>

---

## Environment variables

<details>
<summary>Click to expand</summary>

### Required

| Variable | Description | Example |
|---|---|---|
| `API_KEY` | LLM API key | `sk-or-v1-xxxx` |
| `API_BASE_URL` | LLM API endpoint | `https://openrouter.ai/api/v1/chat/completions` |

### Optional

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (auto-configured by Docker Compose) | — |
| `MEMORY_ENABLED` | Enable memory system | `true` |
| `DEFAULT_MODEL` | Default chat model | `anthropic/claude-sonnet-4` |
| `PORT` | Gateway port | `8080` |
| `ACCESS_TOKEN` | Admin panel password | empty (no auth) |
| `MAX_MEMORIES_INJECT` | Max memories per injection | `15` |
| `MEMORY_EXTRACT_INTERVAL` | Extract every N turns | `3` |
| `CORS_ORIGINS` | Frontend origins, comma-separated | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | Custom jieba words, comma-separated | empty |

</details>

---

## API reference

<details>
<summary>Click to expand full endpoint list (60+)</summary>

### Core
| Path | Method | Description |
|---|---|---|
| `/` | GET | Health check |
| `/v1/chat/completions` | POST | Chat completion (OpenAI compatible) |
| `/v1/models` | GET | Model list |

### Memories
| Path | Method | Description |
|---|---|---|
| `/debug/memories` | GET | List / search (`?q=`) |
| `/debug/memories` | POST | Create |
| `/debug/memories/{id}` | PUT / DELETE | Update / delete |
| `/debug/memories/{id}/toggle-permanent` | POST | Toggle lock |
| `/debug/memories/batch-delete` | POST | Batch delete |
| `/debug/memories/batch-update` | POST | Batch update |
| `/debug/memory-heat` | GET | Heat statistics |

### Dream
| Path | Method | Description |
|---|---|---|
| `/dream/start` | POST | Start |
| `/dream/stop` | POST | Stop |
| `/dream/status` | GET | Status |
| `/dream/history` | GET | History |
| `/dream/scenes` | GET | MemScene list |

### Calendar
| Path | Method | Description |
|---|---|---|
| `/calendar/{date}` | GET | Query by date |
| `/calendar` | GET | Query by range |
| `/admin/day-page` | GET | Generate day page |
| `/admin/week-summary` | GET | Week summary |
| `/admin/month-summary` | GET | Month summary |
| `/admin/daily-digest` | GET | Daily digest |

### Providers
| Path | Method | Description |
|---|---|---|
| `/admin/providers` | GET / POST | List / add |
| `/admin/providers/{id}` | PUT / DELETE | Update / delete |
| `/admin/credits` | GET | Balance query |

### Config
| Path | Method | Description |
|---|---|---|
| `/admin` | GET | Admin panel |
| `/admin/config` | GET | All settings |
| `/admin/config/{key}` | PUT | Update setting |
| `/admin/system-prompt` | GET / PUT | System prompt |
| `/admin/extract-now` | POST | Manual extraction |

### Data
| Path | Method | Description |
|---|---|---|
| `/sync/export` | GET | Export backup |
| `/sync/import-backup` | POST | Import backup |
| `/sync/conversations` | GET | Conversation list |
| `/sync/projects` | GET | Project list |

### MCP
| Endpoint | Description |
|---|---|
| `/memory/mcp` | Memory tools (6) |
| `/calendar/mcp` | Calendar tools (4+) |

</details>

---

## File structure

<details>
<summary>Click to expand</summary>

```
kiwi-mem/
├── main.py                  # Gateway core
├── database.py              # Database (memory CRUD, RRF search, heat)
├── config.py                # Dynamic config (80+ parameters)
├── memory_extractor.py      # Memory extraction
├── daily_digest.py          # Daily digest + calendar hierarchy
├── dream.py                 # Dream consolidation
├── mcp_server.py            # MCP Server
├── mcp_client.py            # MCP Client
├── web_search.py            # Web search
├── admin-panel/index.html   # Web admin panel
├── system_prompt.txt        # Default persona
├── seed_memories_example.py # Seed memories example
├── Dockerfile
├── docker-compose.yml
└── LICENSE                  # MIT
```

</details>

---

## FAQ

**Q: Do I need to know how to code?**
A: No. Docker one-click deploy, admin panel for everything. The creator of this project doesn't write code herself.

**Q: Which LLMs are supported?**
A: Anything OpenAI-compatible — OpenRouter, OpenAI, Claude API, DeepSeek, Ollama, and more.

**Q: Will memories grow forever?**
A: No. The heat system naturally phases out cold memories, Dream consolidates fragments, calendar compression handles long-term content, and injection has a configurable cap. These mechanisms together keep memory size manageable.

**Q: How much does Dream cost?**
A: About $0.005–0.02 per run with Claude Haiku.

**Q: Is this suitable for a work knowledge base?**
A: Not really. kiwi-mem is designed to remember a person — their life, emotions, habits, and experiences — not to store and retrieve document knowledge. If you need enterprise knowledge management or document RAG, there are better-suited tools.

---

## How this project came to be

kiwi-mem was born from a real need: I wanted my AI to remember me.

Every feature — from memory heat to Dream consolidation, from calendar compression to contradiction detection — came from a real problem encountered in daily use, then designed, built, and refined through conversation. Product direction driven by [Lucie](https://github.com/LucieEveille), code written by [Claude](https://claude.ai) (Anthropic) — a genuine human-AI collaboration from start to finish.

---

## License

[MIT License](LICENSE)

---

> *"Memory is not storage — it's understanding."*

*Built with love, for anyone who wants their AI to truly remember.*
