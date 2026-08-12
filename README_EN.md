# 🥝 kiwi-mem

**Most AI memory systems are databases. kiwi-mem is a brain.**

[中文版 →](README.md)

---

## What it does

kiwi-mem gives your AI long-term memory that works like a human brain.

Not "save chat logs and search them later" — actually human-like: things you don't mention gradually fade, things you talk about often stick harder, a night of sleep reorganizes scattered fragments into deeper understanding, last year's events compress into rough outlines while yesterday stays vivid.

All of these mechanisms work together as a unified filtering system: **your AI remembers what you'd remember, and forgets what neither of you would care about.** Without blowing up the context window or burning through your API budget.

Technically, it's a lightweight proxy gateway that sits between you and any LLM, compatible with both OpenAI-format and Anthropic-native providers. Docker one-click deploy, browser-based admin panel.

**Stack**: Python / FastAPI · PostgreSQL + pgvector · Docker · AGPL-3.0-or-later

![Feature overview](docs/feature-overview2.png)

---

## Why kiwi-mem exists

Your AI's memories belong to you — not to a platform.

kiwi-mem is built so that anyone can self-host, audit, and migrate their AI's long-term memory. No vendor lock-in, no black-box storage, no dependence on services that might disappear tomorrow.

If an AI remembers you, you should be able to see what it remembers, decide what it keeps, and take it with you when you leave.

---

## How memory works like a brain

The core of kiwi-mem isn't any single feature — it's multiple mechanisms working in concert to make AI memory behave like human intuition:

### 🔥 Fades and strengthens

Every memory has a "heat" score. Time makes it naturally decay, but if you keep bringing up the same topic, it warms back up. High-emotion memories decay slower — just like how you remember moments that moved you. And fading isn't an on/off switch: aging memories are gently blurred each night, details softening while key facts remain; if a blurred memory gets recalled in conversation, it automatically earns another 30 days. Only memories actually written into the conversation count as "recalled" — only the cold and old get cleaned up, by heat. Forgetting is gradual, like it is for people. Heat also determines how memories enter the conversation: hot memories get injected in full, warm ones as summaries, cold ones stay quiet.

### 🌙 Sleeps and wakes up smarter

Dream simulates how the human brain consolidates memories during sleep. It works in three layers: first cleans up outdated and duplicate fragments, then merges related fragments into coherent "memory scenes", and finally infers things you never explicitly said but your AI should understand. You can trigger it manually, or let the system decide when it's time to sleep. And dreams aren't forgotten on waking — consolidated scenes carry vector indexes, so when a related topic comes up during the day, they get found and flow back into the conversation. Sleep's output returns to waking life. That's what consolidation is for.

### 📅 Recent is vivid, distant is hazy

The calendar system auto-compresses chat history into hierarchical summaries: day → week → month → quarter → year. When injecting into conversation, recent days get full detail, last week gets abbreviated, older periods get high-level overviews. Just like how you recall the past — you know what you ate yesterday, but last month is mostly outlines.

### 🧩 Contradictions update, important things stick

When a new memory conflicts with an old one (you changed jobs, moved cities), the system auto-invalidates the outdated version. Memories you lock by hand are sacred — they never decay, never retire, never auto-delete. Machine-locked memories (auto-locks and Dream promotions) have an exit path instead: if nobody asks about them for 90 days, they get demoted from "permanent" back to high-importance regular memories (reversible, never deleted), freeing precious injection space for what's actually alive.

### ⚡ Budget and context aware

All static content (persona, profile, locked memories, calendar summaries) is ordered first in the prompt to hit cache, dynamic content (search results, drowsiness hints) comes after. This injection order can save up to 90% on API input costs. Combined with calendar compression and heat-tiered injection, even months of memories won't overflow your context window.

### 🔌 Not just OpenAI — direct Anthropic too

Most AI memory solutions only work with OpenAI-format APIs. kiwi-mem also supports Anthropic's native format — if you have an Anthropic API key, you can connect directly without a relay or proxy. Just select "Anthropic native" when adding a provider in the admin panel, and kiwi-mem handles all format differences, including streaming and tool use.

> ⚠️ Anthropic native format must be configured through the admin panel (select "Anthropic native" when adding a provider). Environment variable configuration only works with OpenAI-compatible providers.

### 🧰 Only the tools you need, when you need them

kiwi-mem has 20+ built-in tools (memory search, calendar queries, reminders, web search, etc.). Loading all of them into every conversation wastes hundreds of tokens on tool descriptions the model won't even use.

The Tool Drawer takes a smarter approach: for each message, it quickly figures out which tools you might need and only loads those. The rest stay in the drawer. Like a chef who doesn't put every spice on the counter — just the ones they need right now.

Off by default. Turn it on in the admin panel under Config if you want it.

### 🔒 Projects stay in their lane

If you use the project feature to separate different contexts (work in one project, daily life in another, fiction writing in a third), their memories are now fully isolated. Client info from your work project won't leak into casual conversations, Dream only consolidates fragments within the same project, and daily digests and locked memories follow the same rule.

No setup needed — isolation is automatic.

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
- An LLM API key (OpenRouter / OpenAI / DeepSeek / Anthropic / any compatible provider)

> 💡 Two connection modes: OpenAI-compatible format (most providers) and Anthropic native format (direct API connection, no relay needed). Choose in the admin panel when adding a provider.

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

> 🔓 **kiwi-mem has no built-in authentication.** If you expose it to the public Internet, protect the entire service with Cloudflare Access, reverse-proxy Basic Auth, or an IP allowlist. Pay special attention to `/admin`, `/sync/export` (which may export API keys in the full configuration backup), and `/sync/import-backup` (which restores the full configuration). These endpoints are not authenticated by kiwi-mem itself.

> 💡 80+ parameters can be changed at runtime via the admin panel — no restart needed.

### Staying up to date

kiwi-mem ships updates regularly. Once deployed, keep up with one command — no technical knowledge required, and nothing is lost.

**Set it and forget it (recommended):**

```bash
cd kiwi-mem && bash scripts/update.sh --install-cron
```

Your server now checks for new versions every night at 4 AM and updates itself when there is one. Progress is logged to `update.log`. To stop: `crontab -e` and delete the line containing `update.sh`.

**Or update manually whenever you want:**

```bash
cd kiwi-mem && bash scripts/update.sh          # shows what's new, then asks to confirm
cd kiwi-mem && bash scripts/update.sh --check  # just check, don't touch the service
cd kiwi-mem && bash scripts/update.sh --help   # all options
```

**Your data is safe.** Updates replace code only:

- Memories, conversations, calendar pages and Dream results live in a Docker volume — untouched
- `.env` is git-ignored and never overwritten
- Providers, API keys and the 80+ runtime parameters live in the database — preserved as-is
- **Schema migrations run automatically** on startup (`init_tables()` is idempotent), so new columns appear on their own
- The script **backs up the database before every update** into `backups/` (keeping the 7 most recent)
- If the new version fails to start, the script **rolls back automatically** — you never end up with a half-updated service

> ⚠️ Don't hand-edit tracked files (`main.py`, `docker-compose.yml`, …). The script stops and warns you instead of silently overwriting them. Configure through `.env` or the admin panel instead.

**On Zeabur or similar platforms:** skip the script — just enable Auto Deploy in the project settings and every push redeploys automatically.

**Getting notified:** on GitHub, click **Watch → Custom → Releases** to get an email when a new version ships.

### Importing existing memories

Want to bring in memories from previous AI conversations? Two ways:

**Option 1: Add via admin panel (recommended)**

Open `/admin` → click 🧠 Memories in the sidebar → **+ Add Memory** in the top right → fill in title, content, and importance → Save.

Best for a small number of memories. What you see is what you get.

**Option 2: Bulk import**

Memory import is being rebuilt and will return in a future version in a smarter form.

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
- Only memories actually injected into the prompt count as recalled; recalled low-resolution memories are extended by 30 days
- Tiered injection (hot → full text / warm → summary / cold → skip)
- Nightly softening can progressively compress old memories, with a 21-day cooldown by default; old embeddings are kept if regeneration fails
- User locks never retire; auto locks and Dream-promoted locks can retire after 90 days without recall, but are not deleted
- Dream merge outputs keep a default floor of 20 items, and MemScenes can flow back into normal chat by vector similarity

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
- OpenAI-compatible and Anthropic native format support
- One-click provider connection test in admin panel
- Balance queries, model grouping

### 🧰 Tool Drawer
- Vector similarity determines which tools each turn needs
- 20+ internal tools loaded on demand, not all at once
- External MCP servers are best stored in the `mcp_servers` config key; once the drawer is enabled, they become dynamic drawer categories
- `mcp_mode` only controls config-source external drawers: `off` excludes them, `auto` routes by vector/keyword plus pinned IDs, and `manual` keeps only pinned IDs
- Request-body `mcp_servers` remain supported as the backward-compatible path for third-party frontends and are treated as explicit input, so they are not governed by `mcp_mode`
- Off by default, one-click toggle in admin panel

### 🔒 Project memory isolation
- Different projects have fully isolated memories
- Dream, daily digest, and locked memory injection all respect project scope
- No manual config needed — automatic on project creation

### 🔧 Tools & extensions
- MCP Server (20+ tools) + MCP Client
- Web search (7 engines)
- Context compression, file parsing, chain-of-thought display

### 🛡️ Deployment & management
- Web admin panel · cloud sync · backup/restore
- Reminder system · Docker deploy

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
| `MAX_MEMORIES_INJECT` | Max memories per injection | `15` |
| `MEMORY_EXTRACT_INTERVAL` | Extract every N turns | `3` |
| `CORS_ORIGINS` | Frontend origins, comma-separated | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | Custom jieba words, comma-separated | empty |
| `CLEANUP_HEAT_THRESHOLD` | Low-heat cleanup threshold | `0.15` |
| `AUTO_SOFTEN_ENABLED` | Enable automatic softening | `true` |
| `AUTO_SOFTEN_DAILY_LIMIT` | Daily softening limit | `10` |
| `AUTO_SOFTEN_MIN_AGE` | Minimum age before softening, in days | `5` |
| `SOFTEN_COOLDOWN_DAYS` | Softening cooldown, in days | `21` |
| `LOCK_RETIRE_ENABLED` | Enable auto / Dream lock retirement | `true` |
| `LOCK_RETIRE_DAYS` | Lock retirement age, in days | `90` |
| `MERGE_RETENTION_DAYS` | Dream merge retention age, in days | `90` |
| `MERGE_MIN_KEEP` | Minimum Dream merge memories to keep | `20` |
| `SCENE_INJECT_ENABLED` | Enable MemScene injection | `true` |
| `SCENE_INJECT_LIMIT` | MemScenes injected per turn | `2` |
| `SCENE_INJECT_MIN_SIM` | MemScene similarity threshold | `0.5` |
| `EXT_DRAWER_THRESHOLD` | External drawer similarity threshold | `0.40` |
| `EXT_DRAWER_MAX_OPEN` | Max external drawers opened per turn | `3` |
| `mcp_servers` | External MCP server JSON array (recommended via admin panel) | empty |
| `mcp_manual_ids` | External drawer IDs / names to pin open | empty |
| `mcp_mode` | Config-source external MCP mode (`off` / `auto` / `manual`) | `auto` |
| `reminder_tools_enabled` | Global reminder-tools switch shared by classic and drawer modes | `true` |

</details>

> PostgreSQL deployment tip: consider enabling `client_connection_check_interval = '30s'` to reduce startup migration stalls caused by zombie connections holding locks.

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
| `/admin/test-provider/{id}` | POST | One-click connection test |
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
├── anthropic_adapter.py     # Anthropic native format adapter
├── tool_drawer.py           # Tool Drawer (vector-routed on-demand loading)
├── mcp_server.py            # MCP Server
├── mcp_client.py            # MCP Client
├── web_search.py            # Web search
├── admin-panel/index.html   # Web admin panel
├── scripts/update.sh        # One-command updater (auto backup + rollback)
├── system_prompt.txt        # Default persona
├── Dockerfile
├── docker-compose.yml
└── LICENSE                  # AGPL-3.0-or-later
```

</details>

---

## FAQ

**Q: Do I need to know how to code?**
A: No. Docker one-click deploy, admin panel for everything. The creator of this project doesn't write code herself.

**Q: Which LLMs are supported?**
A: Two ways to connect. Most providers (OpenRouter, OpenAI, DeepSeek, Ollama, etc.) use OpenAI-compatible format. Anthropic can connect directly via native API — no relay needed. Choose the format when adding a provider in the admin panel.

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

kiwi-mem is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later).

You may use, copy, modify, and distribute this project. If you modify kiwi-mem and make it available to users over a network, you must also provide those users with the corresponding source code of your modified version. This keeps the backend open for self-hosting and further development, while preventing closed-source service forks.

---

> *"Memory is not storage — it's understanding."*

*Built with love, for anyone who wants their AI to truly remember.*
