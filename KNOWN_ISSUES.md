# 已知问题登记（Known Issues）

本文件登记代码审计发现、但**当前批次有意未修**的项：要么是设计取舍、要么是低危技术债、
要么需要产品决策。修过的高危项见 git 历史，不在此列。

> 行号为审计时的近似位置，经多次改动后可能有偏移，以函数名为准。

---

## 一、设计取舍（不视为 bug）

- **纯 `.env` 部署只支持 OpenAI 格式。** Anthropic 原生必须经管理面板配置供应商
  （README 已说明）。因此以下「硬编码 OpenAI / Bearer」是符合该约束的，不修：
  - `/v1/models` 的环境变量兜底分支（`main.py` `list_models`）用 `Authorization: Bearer`。
  - 切窗摘要压缩的异常兜底（`main.py` 约 3348）固定 `use_api_format="openai"`。
  - `resolve_model_endpoint` 的环境变量兜底（`database.py` 约 3691）。
- **`API_BASE_URL` 默认 OpenRouter** 是零配置默认值，刻意保留。

---

## 二、中危：待产品决策 / 需谨慎处理（暂缓）

> ✅ 工具抽屉 auto 钉选语义分叉、并发快照不完整 —— 两项已在后续小 PR 修复：
> auto 统一为纯语义路由（不读 `mcp_manual_ids`，与 `handle_meta_tool` 一致）、
> 锁内一并快照 `_category_embeddings`/`CATEGORIES`/`TOOL_SCHEMAS`/`_external_categories`，
> 并补了 `tests/test_drawer.py` 行为测试。不再列为待办。

- **矛盾检测漏「纯数字/单字事实更新」**（`database.py` `detect_contradictions`）。
  字符重叠兜底对「我女儿五岁 → 六岁」这类整句几乎相同、只改一个字的更新，会算成
  近重复（>0.85）而漏判。`tests/test_logic.py` 有 INFO 标注当前行为。
  → 根治需语义/数值感知，非字符重叠能解决，留待后续。

---

## 三、低危技术债（登记备查）

> ✅ 已在「顺手清低危」批次修复（不再列为待办）：
> - Dream 软化参数改读已有配置 `auto_soften_*`（不再写死 5/15、不漏 cooldown）
> - `update_user_profile` 回退链补 `default_digest_model`
> - `/admin/credits` 环境兜底改用通用查询 `_query_generic_credits`（不再只认 OpenRouter）
> - OpenAI URL 拼接前归一化后缀（误填 `.../messages`、`.../chat/completions` 不再拼错）
> - 本地搜索解析到 0 条但页面非空时打告警日志（区分「解析失败」与「真无结果」）

### 工具 / MCP / 搜索
- **W2-05b：聊天抽屉的五个记忆工具尚未接项目 scope。** 当前 W2-05 已保证已删或未验证项目进入隔离态，`memory` / `conversation` 两类工具不会暴露；但 global / live project 内部的搜索、保存、最近记忆与锁定/解锁仍沿用旧 MCP 执行器。项目内保存可能落成全局、全局 recent 可能列出项目项。W2-05b 必须在 W2-06a 前关闭这笔债。
- **W2-05 历史与读取合同。** 历史账本行不回填；未知归属行不进新读路径；未带项目默认全局。全局记忆、日历与 Dream 是共享底座，项目私有层单向封闭。scope 每轮只生成一份快照：metadata 与 payload 不一致时按 metadata 读取并记 `scope_mismatch`；已删或未验证项目进入隔离态，只给共享底座。新项目尚未同步完成的首轮会记 `scope_unverified`。
- 外部 MCP **不支持鉴权**：`_normalize_external_servers` 丢弃 `auth`/`headers`，client 也不透传；
  需要 Bearer 的外部 MCP 会 401、且失败被吞成「该 server 无工具」。
  → 属「加能力」而非小修（要给 transport client 透传 header），单独评估，暂留。
- 自家 MCP 靠 URL 子串 `"/memory/mcp"`/`"/calendar/mcp"` 识别（`tool_drawer.py`），改挂载路径会失效。
  → 现行挂载下有效，硬化收益有限，暂留。
- 本地搜索引擎正则匹配结果页 class（`web_search.py`），页面改版会解析到 0 条。
  → **已加告警日志**区分「解析失败」与「真无结果」；但正则本身仍随页面改版失效，根治需换解析方式。
- `record_tool_use` 在 session 被 LRU 淘汰后静默 no-op（`tool_drawer.py`）；影响极小，暂留。

### 认知后台（Dream / 整理 / 提取）
- Dream 自动触发 `should_dream` 的 `5/7/3` 阈值硬编码（`dream.py` ~784），与可配的
  `dream_drowsy_threshold`（默认 30）两套标准不一致。
  → 统一需新增配置项 + schema（属功能改动，非「顺手」），留待后续。
- 后台任务兜底默认模型名硬编码 `anthropic/claude-haiku-4`（OpenRouter 命名风格），非 OpenRouter
  供应商上该 model_id 可能 404。→ 改默认值会影响零配置开箱体验，暂留。

## KIWI-SEC-01a scope and remaining security work

- No built-in authentication, env fallback and default upstream addresses are intentional public behavior. Credentials remain plaintext in DB/env; an actor with admin access can retarget a provider using its stored key. Protect the whole service.
- This patch sanitizes the specified credential/model failure paths, not every exception in the repository. KIWI-ERR-01 retains the other 49 main.py error=str(e) exits, six daily_digest.py internal error dictionaries and unlisted MCP/tool failure channels. User-authored text and raw database dumps are not secret-filtered.
- MCP Host/Origin setup and exact route mounting remain BUILD-01/SEC-01b work. Embedding versioning/rebuild remains EMB-01 work.
- Compatibility changes and deployment guidance: [security model](docs/security-model.md).

SEC-01a 补丁批复核记录：供应商新建空名称仍返回原有固定错误串；日历周期校验目前统一为 invalid_request，具体原因的机器码与面板提示留给 KIWI-ERR-01。
