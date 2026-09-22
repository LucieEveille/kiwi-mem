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

<a id="kiwi-lock-01"></a>

### KIWI-LOCK-01：Dream promote 与退休用户锁保护（已修复，集成分支待验收）

修复前的继承链条四步：

1. 用户主动锁定记忆，写入 `is_permanent=TRUE`、`lock_source='user'`。
2. `dream._execute_dream_action` 执行 `promote`，调用 `database.promote_memory`。
3. `promote_memory` 无条件将锁来源覆盖为 `lock_source='dream'`，保留 `is_permanent=TRUE`。
4. 退休任务启用且 `last_accessed` 非空、超过 `lock_retire_days` 时，`daily_digest.retire_stale_locks` 选中该行，将 `is_permanent` 改为 `FALSE`、`lock_source` 清为 `NULL`。

影响面：用户锁会静默失效；上述退休操作不删除记忆。该链条在基线 `f70c476` 已存在，W2-05b 未改 `promote_memory`、`dream.py` 或 `daily_digest.py`；已由 **LOCK-01** 修复：promote 不改写用户锁、不改写非全局行；退休 UPDATE 原子重核永久状态与 auto/dream 来源，计数、标题与日志依据实际更新行。原有历史误改行不回溯修复。

保留边界：退休年龄沿用 SELECT 时的 `last_accessed` 快照；SELECT 后访问时间刷新仍可能被退休，UPDATE 本票只重核永久状态与锁来源。

---

## 三、低危技术债（登记备查）

> ✅ 已在「顺手清低危」批次修复（不再列为待办）：
> - Dream 软化参数改读已有配置 `auto_soften_*`（不再写死 5/15、不漏 cooldown）
> - `update_user_profile` 回退链补 `default_digest_model`
> - `/admin/credits` 环境兜底改用通用查询 `_query_generic_credits`（不再只认 OpenRouter）
> - OpenAI URL 拼接前归一化后缀（误填 `.../messages`、`.../chat/completions` 不再拼错）
> - 本地搜索解析到 0 条但页面非空时打告警日志（区分「解析失败」与「真无结果」）

### 工具 / MCP / 搜索
- **W2-05b：五个聊天抽屉记忆工具的项目 scope 债已修复（集成分支待验收、未发布）。** 私有执行器的可见集合为 global 只全局、live project 为全局＋当前项目；项目保存落当前项目，全局记忆对项目可见可锁，锁定/解锁只更新可见集合，数量按同一可见集合计数并排除已消化、已删除与已过期项。隔离态拒绝及公共 MCP / debug 合同保持。证据：`T-W2-05b-01…07`、`docs/acceptance/evidence/kiwi_w2_05b_knives.json`；机制见 [抽屉 scope](docs/event-ledger-scope-and-reconciliation.md#chat-drawer-memory-scope-w2-05b)。
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
- This patch sanitizes the specified credential/model failure paths, not every exception in the repository. KIWI-ERR-01 handles the enumerated ordinary HTTP exits and six raw internal error dictionaries; unlisted MCP/tool failure channels remain outside this scope. User-authored text and raw database dumps are not secret-filtered.
- MCP Host/Origin setup and exact route mounting remain BUILD-01/SEC-01b work. Embedding versioning/rebuild remains EMB-01 work.
- Compatibility changes and deployment guidance: [security model](docs/security-model.md).

SEC-01a 补丁批复核记录：供应商新建空名称由 ERR-01 改为400 invalid_request；日历周期校验统一invalid_request，细分原因机器码与面板提示归2.0.x #11～#18。

SEC-01a P2：ERR-01 已处理客户端/备份成员解码错误、未知码状态不一致、非ZIP及空query固定串；no_route白名单项保留未使用。观察项暂保留：路径 U+200B 编码、Anthropic 稳定错误二次映射、256B 分块断流丢尾；依赖版本边界由 BUILD-01 处理。

SEC-01a P3 复核登记（本票不改，归2.0.x #5）：OpenAI 的 `data:[DONE]` 无空格变体可能与兜底形成两个 DONE；首行合法、次行垃圾的畸形块可能透传；`data: <html>` 等 SSE 包装的非 JSON 载荷仍可能透传，这两类不在三种裸非 SSE 体拒绝保证内。两分支上游 200 空体仍静默结束；通用账单根路径不剥 `/v1/messages` 后缀（同源但可能路径不兼容）。合法 `id:` / `retry:` / 注释块在 OpenAI 直连流中可原样透传，属协议观察，不当作泄漏修复。

## KIWI-PREP-01

1.7.0 暂留 mcp 1.12.4 的 CVE-2025-66416 / CVE-2026-52869 / CVE-2026-59950，限时例外由 BUILD-01 随 2.0.0 解除；其他扫描结果不豁免。详见 [升级预告](docs/UPGRADING.md)。

预检 fail-open：尚未观察到远程使用、状态口不可达或升级门无法解析时仅提示；登记值存在不证明正确。Zeabur Auto Deploy 和跳过准备版的用户不受预检覆盖。Quick Tunnel 官方不支持 SSE。


## KIWI-BUILD-01

- 集成分支已升 mcp 1.29.1，PREP 的三条 MCP 公告例外在本分支解除；正式用户随 2.0.0 发布取得修复，1.7.0 历史例外仍适用。
- 不内置共享托管后缀（含 zeabur.app / trycloudflare.com），需登记完整域名；Quick Tunnel 不支持 SSE。
- IP 零配置仅适用于没有 Origin 的客户端；Host 校验不等于认证，/v1、/admin、/sync 不因此增加 Host/Origin 拒绝。
- SDK 请求体上限 4 MiB。/calendar/mcp 精确路由已修（SEC-01b，560ec2b，PR #84；集成分支，未发布），本票仅验证 calendar SDK 实例。
- SEC-01a P3 观察项（归2.0.x #5）：只有空白或 : keepalive 的零事件体可能被判 parse_failed；message_start 后混入非 SSE 垃圾会被吞成 role delta + [DONE]。登记后续处理，本票不改。

## KIWI-SEC-01b

- O-6：真机 307（尾斜杠 `/memory/mcp/`、`/calendar/mcp/`、`/calendar/`）的 Location scheme 为 `http`——TLS 在平台 / 反代终止、应用未信任代理头。跟随重定向的客户端可能降到 http。规避：MCP URL 不带尾斜杠。代理头信任（`X-Forwarded-Proto`）评估归 RELEASE-01。
- `/calendar/` 由 404 变 307（Starlette `redirect_slashes`，在门卫之前），不经门卫、不写观察、无安全面；`/calendar/{date}` 非 GET 由 404 变 405。行为变更已写入 CHANGELOG。
- `session_identity` 与本票无关；四本刀账本 schema 不一致（SEC-01a 用 `result` / `--run`）统一归 RELEASE-01。

## KIWI-THINK-01

- 排查 #1～#4 的网关缺省开启、面板未接线与隐式 Anthropic temperature 覆盖已修（5195c66，PR #86；集成分支，未发布）。
- `off` ＝ 网关不主动开启，**不等于强制关闭上游推理**；供应商关闭参数与模型能力归思考档位双仓专项票。`exclude` 只控制是否返回推理内容，不关闭推理。
- 面板档位仍为五档（#69 边界），`xhigh` / `max` 由客户端显式传；面板扩档留给专项票。
- `auto` 对 Anthropic 直连映射 budget 10000 ＋ temperature 1；实际预算受 `max_tokens` 钳制，额度不足时禁用 thinking，详见机制文档。
- 库中历史非法配置值的通用兜底归排查 #10（2.0.x），本票只兜 `reasoning_effort` 一键。`panel` 来源含出厂默认 off，`default` 只表示空 / 非法值兜底。

## KIWI-EMB-01（2.0 集成分支）

向量状态口扫描三表，复杂度 O(N)。格式守门能排除原生 Anthropic，无法判断 OpenAI 格式中转站背后的模型能力。探针诊断不持久化；脱敏只识别凭据原文及 URL 编码，任意编码不保证。worker 内部异常保留 running，等待两分钟租约过期后继续。换模型有每批前/后及结果身份检查，反馈仍可能延后到下一批或重新检查。重新对齐依据当前待处理行，不保证只重试上一轮失败项；新增/变更内容可能改变数量。部署回退前停止新 worker；不要让旧版继续写入同一库并期待其维护新身份。

Status scans are O(N). Native Anthropic format is excluded, but relay capability requires probing. Diagnostics are not persisted and redaction covers literal/URL-encoded credentials only. Unexpected worker failures resume after the two-minute lease expires. Model-change feedback can lag until the next batch/check. Retry re-enumerates current data. Stop new workers before rollback; old application versions do not maintain identity columns.

## KIWI-ERR-01

- 本分支枚举的错误出口已改稳定形，随2.0发布；范围和保留合同见UPGRADING。X1保留嵌套形状、去掉字符串值回显。
- 四个可选体入口空/空白body照旧，非空坏body改400；不再把3953/4166坏体当空体。有效非对象JSON除裁决指定入口外保留现状，归2.0.x。
- W2五处固定响应、记忆系统未启用200、周/月/周期model returned invalid format、embedding-probe200均保留。
- 日历错误子码/面板提示归2.0.x #11～#18；P3 SSE/路径/空体/账单观察归2.0.x #5；路径U+200B与二次映射/分块尾部观察继续登记，不纳入本票证明。
- HTTP/1.1 trace过滤只承诺已验格式中的reason字段；不承诺headers脱敏或全部httpcore版本。
