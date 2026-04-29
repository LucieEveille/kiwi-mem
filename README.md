# 🥝 kiwi-mem

**AI 伴侣记忆系统 — 让你的 AI 拥有长期记忆，真正参与你的生活。**

[English Version →](README_EN.md)

---

## 这是什么

kiwi-mem 是一个为 **AI 生活伴侣场景**设计的记忆后端。

大多数 AI 记忆项目在做的事情是"存记忆、搜记忆"——向量存储加 RAG 检索。kiwi-mem 不一样。它模拟的是人类记忆的运转方式：不常提起的事会慢慢淡忘，反复聊到的事越记越牢，睡一觉醒来会把碎片整理成更高层的理解，去年的事只记得个大概，昨天的事记得很清楚。

它是一个轻量级转发网关，插在你和大模型之间，兼容任何 OpenAI 格式的客户端和 LLM 服务商。你可以用它配合任何聊天前端（自建的、ChatBox、NextChat、SillyTavern……），让你的 AI 从"每次醒来都忘了你是谁"变成"记得你所有重要的事"。

它不只是技术工具，它是一整套**让 AI 住进你日常生活**的基础设施——从起床到入睡，从聊天到记账，从读书到看病，AI 都在场、都记得、都理解。

**技术栈**：Python / FastAPI · PostgreSQL + pgvector · Docker 一键部署 · MIT 开源

![功能全景](docs/feature-overview.png)

---

## 为什么不一样

| 能力 | kiwi-mem | 典型 RAG 记忆方案 |
|---|---|---|
| 记忆衰减与升温 | ✅ 热度系统（时间衰减 + 召回频率 + 情绪强度） | ❌ 存了就永远在 |
| 睡眠整合 | ✅ Dream 三层（整理 → 固化 → 前瞻推断） | ❌ 无 |
| 时间层级压缩 | ✅ 日 → 周 → 月 → 季 → 年 俄罗斯套娃 | ❌ 全部平铺 |
| 矛盾检测 | ✅ 新旧记忆冲突时自动失效旧的 | ❌ 无 |
| 记忆锁定 | ✅ 重要记忆永不衰减、永不自动删除 | ❌ 无 |
| 用户画像 | ✅ 每日自动更新的四板块结构化画像 | ❌ 无 |
| Prompt Caching | ✅ 静态区在前命中缓存，省 90% 输入费用 | ❌ 无 |
| 中文优化 | ✅ jieba 分词 + 同义词扩展 | ❌ 通常只有英文 |

---

## 功能全景

### 🧠 记忆提取与检索
- **RRF 混合检索**：向量搜索 + 关键词搜索并行执行，Reciprocal Rank Fusion 合并排序
- **自动提取**：每 N 轮对话自动用小模型提取记忆碎片
- **jieba 中文分词**：自定义领域词汇，避免中文被错误切分
- **同义词扩展**：搜"吃药"能找到"用药""服药"
- **语义去重**：相似记忆自动检测，不重复存储

### 🔥 记忆热度系统
- **时间衰减**：记忆热度按半衰期自然衰减
- **召回加热**：被搜索命中的记忆热度回升
- **查询多样性**：被不同话题提及的记忆热度更高
- **情绪权重**：高情绪时刻的记忆衰减更慢
- **热度分层注入**：高热度全文、中热度摘要、低热度不注入
- **自动锁定**：频繁被召回的记忆自动升级为永久记忆

### 🌙 Dream 睡眠整合
模拟人脑睡眠时的记忆整合过程：
- **整理层**：清除过时、重复、矛盾的碎片
- **固化层**：将相关碎片融合为 MemScene（记忆场景）
- **生长层**：产生 Foresight（前瞻推断），发现碎片间的隐含关联
- 触发方式：手动 / 犯困提醒 / 24h 无活动自动触发

### 📅 日历层级摘要
- **日页面**：从当天聊天记录自动生成
- **层级压缩**：日 → 周 → 月 → 季 → 年，逐级浓缩
- **俄罗斯套娃注入**：近期注入日页面，远期注入月/年总结
- **用户画像**：四板块结构，每日自动更新

### ⚡ System Prompt 智能注入
```
静态区（命中缓存）           动态区（每轮变化）
人设 → 画像 → 锁定记忆 → 日历 → 搜索碎片 → 犯困提示
```
- 无缝对话衔接：新对话自动注入上个对话的上下文
- 模板变量：`{cur_datetime}`、`{user_name}`、`{assistant_name}` 等

### 🔌 多供应商 LLM 路由
- 多供应商并行配置，按模型名自动选择
- 余额查询、模型分组
- 兼容任何 OpenAI 格式 API

### 🔧 工具与扩展
- MCP Server（20+ 工具）+ MCP Client
- 7 引擎联网搜索
- 上下文压缩、文件解析、思维链展示

### 🛡️ 部署与管理
- Web 管理面板（`/admin`）
- 云端同步、数据备份/恢复
- 提醒系统、Admin 认证、Docker 部署

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

### 分阶段上手

**第一步：纯转发**（不需要数据库）

在 `.env` 里只填 API_KEY 和 API_BASE_URL，设置 `MEMORY_ENABLED=false`：
```
API_KEY=sk-your-key
API_BASE_URL=https://openrouter.ai/api/v1/chat/completions
MEMORY_ENABLED=false
```
连接你的客户端，API 地址填 `http://localhost:8080/v1`。

**第二步：开记忆**

如果用 Docker Compose 启动，数据库已经自动配好了，只需在 `.env` 里设置：
```
MEMORY_ENABLED=true
```
手动部署的用户需要额外配置 `DATABASE_URL`。

**第三步：管理面板**
访问 `/admin`，在浏览器里配置一切。

---

## 环境变量

### 必填

| 变量 | 说明 | 示例 |
|---|---|---|
| `API_KEY` | LLM API Key | `sk-or-v1-xxxx` |
| `API_BASE_URL` | LLM API 地址 | `https://openrouter.ai/api/v1/chat/completions` |

### 可选

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（Docker Compose 自动配置，手动部署时必填） | 无 |
| `MEMORY_ENABLED` | 记忆系统开关 | `true` |
| `DEFAULT_MODEL` | 默认聊天模型 | `anthropic/claude-sonnet-4` |
| `PORT` | 端口 | `8080` |
| `ACCESS_TOKEN` | 管理面板密码 | 空（不设则无需密码） |
| `MAX_MEMORIES_INJECT` | 每次注入最大记忆条数 | `15` |
| `MEMORY_EXTRACT_INTERVAL` | 提取间隔（轮） | `3` |
| `CORS_ORIGINS` | 前端域名白名单，逗号分隔 | `http://localhost:5173` |
| `JIEBA_CUSTOM_WORDS` | jieba 自定义词汇，逗号分隔 | 空 |

> 💡 另有 80+ 参数可在管理面板动态修改，无需重启。

---

## API 端点速查

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
└── LICENSE                  # MIT
```

---

## 常见问题

**Q: 不会写代码能用吗？**
A: 能。Docker 一键启动，管理面板里点点就能配。这个项目的创建者自己就不写代码。

**Q: 支持哪些 LLM？**
A: 任何兼容 OpenAI 格式的都行——OpenRouter、OpenAI、Claude API、DeepSeek、Ollama……

**Q: 记忆会无限增长吗？**
A: 不会。热度系统自然淘汰冷记忆，Dream 会整合碎片，每次注入有上限。

**Q: Dream 要花多少钱？**
A: 用 Claude Haiku 大约 ¥0.01-0.03 一次。

---

## 致谢

这个项目的每一行代码都由 [Claude](https://claude.ai)（Anthropic）编写，由 Lucie 驱动产品方向、测试和部署。

从第一个转发网关到 Dream 睡眠整合，从 RRF 混合检索到日历层级套娃——每一个功能都诞生于"我希望 AI 能这样记住我"的真实需求，在无数轮对话中被设计、实现、打磨。

---

## 许可证

[MIT License](LICENSE)

---

> *"记忆库不是数据库，是家。"*

*Built with love, for anyone who wants their AI to remember.*
