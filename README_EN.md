# 🥝 kiwi-mem

**AI companion memory system — give your AI long-term memory that actually works like human memory.**

[中文版 →](README.md)

---

## What is this

kiwi-mem is a memory backend designed for **AI companion** use cases.

Most AI memory projects do "store and retrieve" — vector storage plus RAG. kiwi-mem is different. It simulates how human memory actually works: things you don't mention gradually fade, things you talk about often stick harder, a night of sleep reorganizes fragments into deeper understanding, and last year's events compress into rough outlines while yesterday stays vivid.

It's a lightweight proxy gateway that sits between you and any LLM, compatible with any OpenAI-format client and provider. Pair it with any chat frontend (custom-built, ChatBox, NextChat, SillyTavern…) and your AI goes from "forgetting who you are every session" to "remembering everything that matters."

It's not just a dev tool — it's the infrastructure for **an AI that lives in your daily life**, present from morning to night, remembering your conversations, your health, your habits, your growth.

**Stack**: Python / FastAPI · PostgreSQL + pgvector · Docker deploy · MIT License

![Feature overview](docs/feature-overview.png)

---

## What makes it different

| Capability | kiwi-mem | Typical RAG memory |
|---|---|---|
| Memory decay & heating | ✅ Heat system (time decay + recall frequency + emotional intensity) | ❌ Stored forever |
| Sleep consolidation | ✅ Dream (cleanup → consolidation → foresight) | ❌ None |
| Temporal compression | ✅ Day → week → month → quarter → year | ❌ Everything flat |
| Contradiction detection | ✅ Auto-invalidates outdated memories | ❌ None |
| Memory locking | ✅ Important memories never decay or auto-delete | ❌ None |
| User profile | ✅ Auto-updated daily, four-section structured portrait | ❌ None |
| Prompt caching | ✅ Static-first injection order, 90% input cost savings | ❌ None |
| Chinese optimization | ✅ jieba segmentation + synonym expansion | ❌ Usually English only |

---

## Features

### 🧠 Memory extraction & retrieval
- **RRF hybrid search**: Vector + keyword search in parallel, merged via Reciprocal Rank Fusion
- **Auto-extraction**: Every N turns, a small model extracts key info as memory fragments
- **jieba Chinese segmentation**: Custom domain vocabulary support
- **Synonym expansion**: Searching "medication" finds "prescription", "drugs", "medicine"
- **Semantic deduplication**: Similar memories detected automatically

### 🔥 Memory heat system
- **Time decay**: Memory heat decays by half-life
- **Recall heating**: Memories gain heat when retrieved
- **Query diversity**: Memories mentioned across different topics heat up more
- **Emotional weight**: High-emotion memories decay slower
- **Tiered injection**: Hot → full text, warm → summary, cold → skip
- **Auto-lock**: Frequently recalled memories auto-promote to permanent

### 🌙 Dream consolidation
Simulates how the human brain consolidates memories during sleep:
- **Cleanup layer**: Remove outdated, duplicate, contradictory fragments
- **Consolidation layer**: Merge related fragments into MemScenes
- **Growth layer**: Generate Foresight — infer future implications from fragment connections
- Triggers: manual / drowsiness reminder / auto after 24h inactivity

### 📅 Calendar hierarchy
- **Day pages**: Auto-generated from daily chat logs
- **Hierarchical compression**: Day → week → month → quarter → year
- **Matryoshka injection**: Recent days injected in detail, distant months as summaries
- **User profile**: Four-section structure, updated daily

### ⚡ Smart system prompt injection
```
Static (cache-friendly)              Dynamic (per-turn)
Persona → Profile → Locked → Calendar → Search results → Drowsy hint
```
- Seamless conversation handoff between chat windows
- Template variables: `{cur_datetime}`, `{user_name}`, `{assistant_name}`

### 🔌 Multi-provider LLM routing
- Multiple providers in parallel, auto-select by model name
- Balance queries, model grouping
- Compatible with any OpenAI-format API

### 🔧 Tools & extensions
- MCP Server (20+ tools) + MCP Client
- Web search (7 engines)
- Context compression, file parsing, chain-of-thought display

### 🛡️ Deployment & management
- Web admin panel at `/admin`
- Cloud sync, data backup/restore
- Reminder system, admin auth, Docker deploy

---

## Quick start

### Prerequisites
- Docker & Docker Compose (recommended), or Python 3.12+
- PostgreSQL (with pgvector extension)
- An LLM API key

### Three steps

```bash
# 1. Clone
git clone https://github.com/LucieEveille/kiwi-mem.git
cd kiwi-mem

# 2. Configure
cp .env.example .env
# Edit .env with your API_KEY and DATABASE_URL

# 3. Launch
docker compose up -d
```

Visit `http://localhost:8080` — if you see `{"status":"running"}`, you're good.

### Step by step

**Step 1: Pure proxy** (no database needed)
```
API_KEY=sk-your-key
API_BASE_URL=https://openrouter.ai/api/v1/chat/completions
```
Point your client to `http://localhost:8080/v1`.

**Step 2: Enable memory** (add PostgreSQL)
```
DATABASE_URL=postgresql://user:pass@host:5432/db
MEMORY_ENABLED=true
```

**Step 3: Admin panel**
Visit `/admin` to configure everything in your browser.

---

## Environment variables

### Required

| Variable | Description | Example |
|---|---|---|
| `API_KEY` | LLM API key | `sk-or-v1-xxxx` |
| `API_BASE_URL` | LLM API endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@host:5432/db` |

### Optional

| Variable | Description | Default |
|---|---|---|
| `MEMORY_ENABLED` | Enable memory system | `false` |
| `DEFAULT_MODEL` | Default chat model | `anthropic/claude-sonnet-4` |
| `PORT` | Gateway port | `8080` |
| `ACCESS_TOKEN` | Admin panel password | empty (no auth) |
| `MAX_MEMORIES_INJECT` | Max memories per injection | `15` |
| `MEMORY_EXTRACT_INTERVAL` | Extract every N turns | `3` |
| `CORS_ORIGINS` | Frontend origins, comma-separated | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | Custom jieba words, comma-separated | empty |

> 💡 80+ additional parameters can be changed at runtime via the admin panel — no restart needed.

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
| `/debug/memory-heat` | GET | Heat statistics |

### Dream
| Path | Method | Description |
|---|---|---|
| `/dream/start` | POST | Start dream |
| `/dream/stop` | POST | Stop dream |
| `/dream/status` | GET | Dream status |
| `/dream/history` | GET | Dream history |
| `/dream/scenes` | GET | MemScene list |

### Calendar
| Path | Method | Description |
|---|---|---|
| `/calendar/{date}` | GET | Query by date |
| `/calendar` | GET | Query by range |
| `/admin/daily-digest` | GET | Run daily digest |
| `/admin/day-page` | GET | Generate day page |
| `/admin/week-summary` | GET | Generate week summary |

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

### MCP
| Endpoint | Description |
|---|---|
| `/memory/mcp` | Memory tools (6) |
| `/calendar/mcp` | Calendar tools (4+) |

</details>

---

## FAQ

**Q: Do I need to know how to code?**
A: No. Docker one-click deploy, admin panel for configuration. The creator of this project doesn't write code herself.

**Q: Which LLMs are supported?**
A: Anything OpenAI-compatible — OpenRouter, OpenAI, Claude API, DeepSeek, Ollama, and more.

**Q: Will memories grow forever?**
A: No. The heat system naturally phases out cold memories, Dream consolidates fragments, and injection has a configurable cap.

**Q: How much does Dream cost?**
A: About $0.005-0.02 per run with Claude Haiku.

---

## License

[MIT License](LICENSE)

---

> *"A memory system is not a database — it's a home."*

*Built with love, for anyone who wants their AI to remember.*
