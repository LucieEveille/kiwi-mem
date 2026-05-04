# 🥝 kiwi-mem

**大多数 AI 记忆系统是数据库。kiwi-mem 是一颗大脑。**

[English Version →](README_EN.md)

---

## 它做了什么

kiwi-mem 让你的 AI 拥有像人脑一样运转的长期记忆。

不是"把聊天记录存起来，用的时候搜一下"——是真的像人一样记东西：不常提起的事会慢慢淡忘，反复聊到的事越记越牢，睡一觉醒来会把零散的碎片整理成更深的理解，去年的事只记得个大概，昨天的事记得很清楚。

所有功能组合在一起，形成了一套完整的筛选机制：**AI 会记住你也会记住的事情，遗忘的都是两个人都不会在意的内容。** 同时不会撑爆上下文窗口，也不会烧穿你的 API 账单。

技术上，它是一个轻量级转发网关，插在你和大模型之间，兼容任何 OpenAI 格式的客户端和 LLM 服务商。Docker 一键部署，管理面板里点点就能配。

**技术栈**：Python / FastAPI · PostgreSQL + pgvector · Docker · MIT 开源

![功能全景](docs/feature-overview.png)

---

## 记忆怎样像人脑一样运转

kiwi-mem 的核心不是某个单一功能，而是多个机制协同运作，让 AI 的记忆行为逼近人类直觉：

### 🔥 会淡忘，也会加深

每条记忆都有"热度"。时间会让它自然衰减，但如果你们反复聊到同一件事，它会重新升温。高情绪浓度的记忆衰减更慢——就像人会更容易记住那些触动过自己的瞬间。热度决定了记忆如何被注入对话：高热度全文注入，中热度只给摘要，冷记忆不打扰你们。

### 🌙 会"睡觉"，醒来变聪明

Dream 模拟人脑睡眠时的记忆整合。它分三层工作：先清理过时和重复的碎片，再把相关的碎片融合成完整的"记忆场景"，最后从这些场景中推断出你没明说过、但 AI 应该理解的事情。你可以手动触发，也可以让它自己判断什么时候该睡了。

### 📅 近的清晰，远的模糊

日历系统把聊天记录自动压缩成层级摘要：日 → 周 → 月 → 季 → 年。注入对话时，最近几天给完整内容，上周给缩略版，更早的只保留高层概括。就像你自己回忆过去——昨天吃了什么记得住，上个月的事只剩轮廓。

### 🧩 矛盾了会更新，重要的不会丢

当新记忆和旧记忆冲突时（比如你换了工作、搬了家），系统会自动让旧的失效。而那些你明确标记为重要的、或被反复提及的记忆，会被锁定——永不衰减，永不自动清除。

### ⚡ 省钱，也省上下文

所有静态内容（人设、画像、锁定记忆、日历摘要）排在 prompt 前部命中缓存，动态内容（搜索结果、犯困提示）排在后面。这个注入顺序让你的 API 输入费用最多能省 90%。配合日历压缩和热度分层，一个月的记忆量也不会撑爆上下文窗口。

---

## 适合谁用

kiwi-mem 擅长的是**记住一个人**——你的习惯、偏好、情绪、经历、成长轨迹。它不是企业知识库，不做文档检索，不搭知识图谱。

它最适合这些场景：

🏠 **生活助理** — 记住你的饮食习惯、健康状况、日程偏好，用得越久越懂你的生活节奏

🩶 **长期陪伴** — 情感支持、日常闲聊、深度关系，AI 真的"认识你"而不是每次从头开始

📖 **创作伙伴** — 连载小说、世界观构建、角色扮演，所有设定和剧情线都记得住

🎓 **学习辅导** — 记住你的学习进度、薄弱环节、问过的问题，辅导越来越有针对性

---

## 快速开始

### 前置要求

- Docker & Docker Compose（推荐，自带 PostgreSQL + pgvector）
- 一个 LLM API Key（OpenRouter / OpenAI / DeepSeek / 其他 OpenAI 格式兼容服务商）

> 💡 不用 Docker？也可以手动部署：需要 Python 3.12+ 和自己搭建的 PostgreSQL（需要 pgvector 扩展）。

### 三步启动

```bash
# 1. 克隆
git clone https://github.com/LucieEveille/kiwi-mem.git
cd kiwi-mem

# 2. 配置
cp .env.example .env
# 编辑 .env，填入你的 API_KEY（其他配置都有默认值）

# 3. 启动
docker compose up -d
```

访问 `http://localhost:8080` 看到 `{"status":"running"}` 就成功了。

### 然后呢

- 访问 `/admin` 打开管理面板，在浏览器里配置一切
- 把你的聊天客户端的 API 地址指向 `http://localhost:8080/v1`
- 兼容任何 OpenAI 格式的前端：ChatBox、NextChat、SillyTavern，或者你自己写的

> 💡 80+ 参数可在管理面板动态修改，无需重启。

---

## 和其他方案有什么不同

<details>
<summary>点击展开对比表</summary>

| 能力 | kiwi-mem | 典型 RAG 记忆方案 |
|---|---|---|
| 记忆衰减与升温 | ✅ 热度系统（时间衰减 + 召回频率 + 情绪强度） | ❌ 存了就永远在 |
| 睡眠整合 | ✅ Dream 三层（整理 → 固化 → 前瞻推断） | ❌ 无 |
| 时间层级压缩 | ✅ 日 → 周 → 月 → 季 → 年 | ❌ 全部平铺 |
| 矛盾检测 | ✅ 新旧记忆冲突时自动失效旧的 | ❌ 无 |
| 记忆锁定 | ✅ 重要记忆永不衰减 | ❌ 无 |
| 用户画像 | ✅ 每日自动更新的结构化画像 | ❌ 无 |
| Prompt Caching | ✅ 静态区在前命中缓存，省 90% 输入费用 | ❌ 无 |
| 上下文控制 | ✅ 热度分层 + 日历压缩，不撑爆窗口 | ❌ 容易超限 |

</details>

---

## 完整功能列表

<details>
<summary>点击展开</summary>

### 🧠 记忆提取与检索
- **RRF 混合检索**：向量搜索 + 关键词搜索并行，Reciprocal Rank Fusion 合并排序
- **自动提取**：每 N 轮对话自动提取记忆碎片
- **jieba 中文分词**：自定义领域词汇
- **同义词扩展**：搜"吃药"能找到"用药""服药"
- **语义去重**：相似记忆自动检测

### 🔥 记忆热度系统
- 时间衰减（半衰期）· 召回加热 · 查询多样性 · 情绪权重
- 热度分层注入（高→全文 / 中→摘要 / 低→不注入）
- 频繁召回自动升级为永久记忆

### 🌙 Dream 睡眠整合
- 整理层（清除过时 / 重复 / 矛盾碎片）
- 固化层（碎片 → MemScene 记忆场景）
- 生长层（Foresight 前瞻推断）
- 触发：手动 / 犯困提醒 / 24h 无活动自动触发

### 📅 日历层级摘要
- 日页面自动生成 · 日→周→月→季→年逐级压缩
- 俄罗斯套娃注入（近期详细，远期概括）
- 用户画像四板块结构，每日更新

### ⚡ System Prompt 智能注入
- 静态区（人设→画像→锁定记忆→日历）命中缓存
- 动态区（搜索碎片→犯困提示）每轮更新
- 新对话自动衔接上次聊天上下文
- 模板变量支持

### 🔌 多供应商 LLM 路由
- 多供应商并行配置，按模型名自动选择
- 余额查询、模型分组
- 兼容任何 OpenAI 格式 API

### 🔧 工具与扩展
- MCP Server（20+ 工具）+ MCP Client
- 7 引擎联网搜索
- 上下文压缩、文件解析、思维链展示

### 🛡️ 部署与管理
- Web 管理面板 · 云端同步 · 数据备份/恢复
- 提醒系统 · Admin 认证 · Docker 部署

</details>

---

## 环境变量

<details>
<summary>点击展开</summary>

### 必填

| 变量 | 说明 | 示例 |
|---|---|---|
| `API_KEY` | LLM API Key | `sk-or-v1-xxxx` |
| `API_BASE_URL` | LLM API 地址 | `https://openrouter.ai/api/v1/chat/completions` |

### 可选

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（Docker Compose 自动配置） | — |
| `MEMORY_ENABLED` | 记忆系统开关 | `true` |
| `DEFAULT_MODEL` | 默认聊天模型 | `anthropic/claude-sonnet-4` |
| `PORT` | 端口 | `8080` |
| `ACCESS_TOKEN` | 管理面板密码 | 空（不设则无需密码） |
| `MAX_MEMORIES_INJECT` | 每次注入最大记忆条数 | `15` |
| `MEMORY_EXTRACT_INTERVAL` | 提取间隔（轮） | `3` |
| `CORS_ORIGINS` | 前端域名白名单 | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | jieba 自定义词汇 | 空 |

</details>

---

## API 端点

<details>
<summary>点击展开完整端点列表（60+）</summary>

### 核心
| 路径 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 健康检查 |
| `/v1/chat/completions` | POST | 聊天转发 |
| `/v1/models` | GET | 模型列表 |

### 记忆
| 路径 | 方法 | 说明 |
|---|---|---|
| `/debug/memories` | GET | 列表 / 搜索（`?q=`） |
| `/debug/memories` | POST | 创建 |
| `/debug/memories/{id}` | PUT / DELETE | 更新 / 删除 |
| `/debug/memories/{id}/toggle-permanent` | POST | 锁定切换 |
| `/debug/memories/batch-delete` | POST | 批量删除 |
| `/debug/memories/batch-update` | POST | 批量更新 |
| `/debug/memory-heat` | GET | 热度统计 |

### Dream
| 路径 | 方法 | 说明 |
|---|---|---|
| `/dream/start` | POST | 开始 |
| `/dream/stop` | POST | 中止 |
| `/dream/status` | GET | 状态 |
| `/dream/history` | GET | 历史 |
| `/dream/scenes` | GET | MemScene 列表 |

### 日历
| 路径 | 方法 | 说明 |
|---|---|---|
| `/calendar/{date}` | GET | 按日期查询 |
| `/calendar` | GET | 按范围查询 |
| `/admin/day-page` | GET | 生成日页面 |
| `/admin/week-summary` | GET | 周总结 |
| `/admin/month-summary` | GET | 月总结 |
| `/admin/daily-digest` | GET | 每日整理 |

### 供应商
| 路径 | 方法 | 说明 |
|---|---|---|
| `/admin/providers` | GET / POST | 列表 / 添加 |
| `/admin/providers/{id}` | PUT / DELETE | 更新 / 删除 |
| `/admin/credits` | GET | 余额查询 |

### 配置
| 路径 | 方法 | 说明 |
|---|---|---|
| `/admin` | GET | 管理面板 |
| `/admin/config` | GET | 所有配置 |
| `/admin/config/{key}` | PUT | 修改配置 |
| `/admin/system-prompt` | GET / PUT | 人设读写 |
| `/admin/extract-now` | POST | 手动提取 |

### 数据
| 路径 | 方法 | 说明 |
|---|---|---|
| `/sync/export` | GET | 导出备份 |
| `/sync/import-backup` | POST | 导入备份 |
| `/sync/conversations` | GET | 对话列表 |
| `/sync/projects` | GET | 项目列表 |

### MCP
| 端点 | 说明 |
|---|---|
| `/memory/mcp` | 记忆系统工具（6 个） |
| `/calendar/mcp` | 日历系统工具（4+ 个） |

</details>

---

## 文件结构

<details>
<summary>点击展开</summary>

```
kiwi-mem/
├── main.py                  # 网关核心
├── database.py              # 数据库（记忆 CRUD、RRF 检索、热度）
├── config.py                # 动态配置（80+ 参数）
├── memory_extractor.py      # 记忆提取
├── daily_digest.py          # 每日整理 + 日历层级
├── dream.py                 # Dream 睡眠整合
├── mcp_server.py            # MCP Server
├── mcp_client.py            # MCP Client
├── web_search.py            # 联网搜索
├── admin-panel/index.html   # Web 管理面板
├── system_prompt.txt        # 默认人设
├── seed_memories_example.py # 预置记忆示例
├── Dockerfile
├── docker-compose.yml
└── LICENSE                  # MIT
```

</details>

---

## 常见问题

**Q: 不会写代码能用吗？**
A: 能。Docker 一键启动，管理面板里点点就能配。这个项目的创建者自己也不写代码。

**Q: 支持哪些 LLM？**
A: 任何兼容 OpenAI 格式的都行——OpenRouter、OpenAI、Claude API、DeepSeek、Ollama……

**Q: 记忆会无限增长吗？**
A: 不会。热度系统自然淘汰冷记忆，Dream 整合碎片，日历压缩长期内容，每次注入有上限。这些机制共同保证记忆量始终可控。

**Q: Dream 要花多少钱？**
A: 用 Claude Haiku 大约 ¥0.01–0.03 一次。

**Q: 适合用来做工作知识库吗？**
A: 不太适合。kiwi-mem 擅长的是记住一个人的生活、情感、习惯和经历，而不是存储和检索文档知识。如果你需要企业知识库或文档 RAG，有更合适的工具。

---

## 这个项目是怎么来的

kiwi-mem 诞生于一个真实的需求：让 AI 记住我。

每一个功能——从记忆热度到 Dream 睡眠整合，从日历套娃到矛盾检测——都来自日常使用中遇到的真实问题，然后在对话中被设计、实现、打磨。产品方向由 [Lucie](https://github.com/LucieEveille) 驱动，代码由 [Claude](https://claude.ai)（Anthropic）编写，是一次完整的 human-AI collaboration。

---

## 许可证

[MIT License](LICENSE)

---

> *"记忆不是存储，是理解。"*

*Built with love, for anyone who wants their AI to truly remember.*
