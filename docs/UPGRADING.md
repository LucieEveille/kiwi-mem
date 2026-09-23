# 1.7.0 准备版与 2.0 升级预告

本页为 2.0 预告；1.7.0 不改变任何访问行为：不启用 Host / Origin 保护，保留现有无认证与环境变量回落。静态资源随 Starlette 升级支持 Range 请求（206 / 416 / `Accept-Ranges`），属标准 HTTP 行为，非访问控制变更。框架安全修补仍可能改变恶意或畸形请求的错误处理；正常部署的访问规则保持不变。

Zeabur Auto Deploy 不经过 update.sh；长期未更新的用户可能从 1.6.2 直接跳过准备版。两类用户请在升级 2.0 前自行完成下列登记。观察数据只记录是否见过远程域名与最近时间，不存地址；未观察到访问不能证明无人使用。

## 提前登记 MCP 访问地址

2.0 计划只接受登记的 MCP 访问地址。本机与 IP 直连无需域名登记（IP 自动放行仍须通过 BUILD-01 对抗验证）；这里的零配置只适用于不发送 Origin 的工具客户端。浏览器类客户端仍须登记 Origin，Host 登记不代替 Origin 登记，也不代替认证。

Docker Compose 部署，在宿主机 .env 添加：

```dotenv
MCP_ALLOWED_HOSTS=kiwi.example.com
MCP_ALLOWED_ORIGINS=https://kiwi.example.com
```

再运行 `docker compose up -d --build`。单独 `restart` 不会刷新容器环境变量。多个条目用逗号分隔；Host 可带端口（例如 `kiwi.example.com:8080`）或 `:*`，IPv6 用方括号；不支持 `*` 或子域通配。Origin 要包含 http/https 协议及实际端口。

Zeabur 可在环境变量中登记 `MCP_ALLOWED_HOSTS=${ZEABUR_WEB_DOMAIN}`；浏览器来源按实际 Origin 登记。原生 Python 启动不自动加载 .env，请先 `export MCP_ALLOWED_HOSTS=kiwi.example.com` 等变量，再启动程序。临时域名变化后也需更新登记。

## 更新脚本如何处理

登记采用 DNS ASCII 主机名；国际化域名请使用浏览器实际请求中的 Punycode（`xn--`）形式。更新辅助逻辑支持宿主机 Python 3 或 jq；两者都没有时预检会标记未能验证，若脚本自身需要续跑则安全退出并恢复原代码，不能宣称升级已完成。

预检发生在工作树更新、备份与容器操作之前。只有“已观察到远程访问、待部署配置无合法 Host 登记、目标 commit 带访问规则破坏性标记”同时成立才拦截：`--auto` 返回 3；手动运行默认取消，也可明确继续。改好 .env 后重新运行即可。

脚本优先读 `docker compose config --format json` 的渲染值；不可用时把 .env 当数据解析，shell 环境变量优先。登记项存在不等于正确，填错域名仍可能通过预检。状态不可达、非 JSON、未观察到远程访问或升级门无法判定时仅告警继续，这不是防止访问中断的保证。

脚本更新后会携带原 commit、目标 commit、备份与阶段状态重新执行；成功或回滚后删除 `.update-state.json`。健康检查在首页之外发有时限的 MCP initialize POST，只证明本地进程与挂载可用，不证明远程地址可达。

从 1.6.2 升 1.7.0 时仍由旧脚本运行，旧脚本不具备续跑或 MCP 探针。本票不宣称能追溯修复旧脚本。

## 更新探针端口与配置边界

更新脚本保留操作员传入的 `PORT` 环境变量（包括未设置与显式空值的区别），内部探针使用 `LISTEN_PORT`。Python、jq、无助手三条路径都按 shell `PORT` → `.env` 最后一条 `PORT` → 8080 取值；显式空值及无效端口回退 8080。支持 UTF-8 BOM、CRLF、成对单/双引号，端口须为 1～65535 的十进制整数。续跑沿用已保存的探针端口，仍保留操作员环境。

这里限定的是更新辅助解析器支持的数据格式，不是完整的 Compose dotenv 语法：行尾注释、`export PORT=...` 前缀、变量插值不在支持范围。请将端口写为独立的 `PORT=9000` 行；不会执行 `.env` 中的 shell 表达式。Compose 本身可能接受更广的语法；非法端口也可能被 Compose 拒绝，不能把探针的 8080 回退当成部署配置已验证。

Starlette 升级还使 `/admin` 静态资源支持 HTTP Range：有效范围可返回 206，越界范围可返回 416，并增加 `Accept-Ranges`。这是标准 HTTP 静态文件行为变化，未新增访问控制。

The updater preserves the operator's `PORT` environment, including unset versus explicitly empty values, and uses `LISTEN_PORT` internally. Python, jq and helper-free paths use shell `PORT`, then the last dotenv definition, then 8080; empty or invalid values fall back to 8080. UTF-8 BOM, CRLF and paired quotes are supported. Resume retains the saved probe port and the original environment. Trailing comments, an `export` prefix and interpolation are outside the helper's supported dotenv subset; use a standalone `PORT=9000` line. This is not a claim of complete Compose grammar compatibility or successful deployment validation.

After the Starlette upgrade, `/admin` static resources support Range responses (206 for valid ranges, 416 for unsatisfiable ranges) and `Accept-Ranges`. This is a standard HTTP behavior change, not a new access restriction.

## 临时隧道使用说明

Cloudflare Quick Tunnel 官方不支持 SSE，聊天流式与 MCP 不保证可用。仅作为试用方式，正式部署使用自有域名或平台域名。参见 [Quick Tunnels 文档](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)。

## 1.7.0 限时风险例外

1.7.0 暂留 `mcp==1.12.4`，其三条公告 CVE-2025-66416 / CVE-2026-52869 / CVE-2026-59950 仍在。理由：升 mcp ≥ 1.23 会让 SDK 对本机 host 自动开启 Host / Origin 保护、远程 MCP 在准备版就被拒，违背“先提醒再改规则”。解除条件：KIWI-BUILD-01 合入 `release/kiwi-sync` 并随 2.0.0 发布。负责票：BUILD-01。本例外不豁免其他任何扫描结果。

## English: 2.0 notice

1.7.0 previews MCP address registration without enabling access controls. Register your deployment hostname in `MCP_ALLOWED_HOSTS`; browser clients also need `MCP_ALLOWED_ORIGINS`. Compose users must recreate containers with `docker compose up -d --build`; native Python users must export the variables. Zeabur can reference `${ZEABUR_WEB_DOMAIN}`.

The updater blocks automatic upgrades only when remote access was observed, no valid hostname is configured, and the target enables the breaking-change gate. A registered hostname may still be wrong. Missing observations or failed checks are not evidence of readiness. Zeabur auto-deploy and users skipping 1.7.0 bypass this preflight. Quick Tunnel does not support SSE. The temporary MCP security exception above remains until BUILD-01 ships with 2.0.0; no other audit findings are exempt.

## 2.0 MCP 访问控制（集成分支已启用，待发布）

MCP 只接受登记过的访问地址；未配置时先接受本机地址（含 IP 直连）。IP 零配置只适用于不带 Origin 的非浏览器客户端，以及托管在内置本机源（localhost / 127.0.0.1 / [::1]，任意端口）的浏览器页面；其他浏览器来源仍须登记 Origin。本机制不是登录认证，公版管理面和数据接口仍须用部署边界保护。

Compose 三步：
1. 在宿主机 `.env` 写 `MCP_ALLOWED_HOSTS=kiwi.example.com`（含实际端口时一起写，或 `kiwi.example.com:*`）。
2. 浏览器客户端另写 `MCP_ALLOWED_ORIGINS=https://client.example.com`，填客户端真实来源，不自动等同于服务域名。
3. 执行 `docker compose up -d --build` 重建容器，再以有界 initialize POST 验证。仅 restart 不更新容器环境。

原生 Python：先 export 两变量再启动；Zeabur 环境变量页可填 `MCP_ALLOWED_HOSTS=${ZEABUR_WEB_DOMAIN}`，实际展开效果须部署验收。多域名用逗号，临时域名变化后更新；永久 cloudflared 隧道的 `httpHostHeader` 可改变应用收到的 Host，按实收值登记。大小写及端口须与 Host 原值一致，不接受整个共享托管后缀。Quick Tunnel 不支持 SSE，仍只作为试用路径。

| HTTP | error / error_code | 处理 |
| --- | --- | --- |
| 421 | mcp_host_not_allowed | 检查 MCP_ALLOWED_HOSTS、端口、重复或畸形 Host |
| 403 | mcp_origin_not_allowed | 登记客户端实际 Origin |
| 400 | invalid_content_type | POST 使用 application/json，无前导空白 |

421/403 另有固定 hint 指向本指南；回包不含请求头值。大写 APPLICATION/JSON 虽通过安全层，仍被 SDK 协议层以 415 拒绝；不要改写它规避协议校验。请求体上限由 SDK 控制为 4 MiB。

### 状态口与观察表

`GET /admin/mcp-access-status` 固定九键：protection（本分支 enabled）、version（当前服务版本）、hosts_registered / origins_registered（合法登记项数）、hosts_invalid / origins_invalid（非法项数）、ip_literal_allowed、foreign_host_seen、foreign_host_last_seen_at。只回数量、布尔与时间，不回地址。`mcp_access_observation` 是独立单行表，存“是否见过非本机非 IP Host”与最近记录时间，观察写入有 60 秒节流；被拒请求也会观察，存储故障不改变访问裁决。

`MCP_AUTH_TOKEN` 已于 SEC-01a (#80) 删除，原变量从未参与校验，部署配置残留可删。`upgrade_gates.json` 仍为 false，由 RELEASE-01 在正式 2.0 升级时置 true；`/calendar/mcp` 自 SEC-01b (#84) 起 GET / POST / DELETE 均到达 MCP，与 `/memory/mcp` 同形；`/memory` 不再重定向。

### 2.0 思考强度

2.0 起网关缺省不再主动开启思考：客户端未提供非 null 的 `reasoning_effort` 或 `reasoning` 时按面板「思考强度」（默认 off）；依赖缺省开思考的客户端请显式传值或在面板选档。模型自身默认推理的行为不受影响。Anthropic 直连不再在你没开思考时把 temperature 改成 1。

`reasoning_effort` 接受 `none`（off）与 `minimal`（有损映射到 low）。`reasoning` 对象按 `enabled:false` → off、`effort` → 同档（含别名）、仅有 `max_tokens` → 预算下界取档解析；1–4999 按 low，最低映射预算为 5000，不保证满足较小预算。合法字符串入口优先于对象；null 视同缺席。`off` 表示网关不发思考字段，不保证模型不推理。`max_tokens:0` 按关闭；空对象、全 null 或只有未知字段按面板。对象内无法识别的 `enabled` / `max_tokens` 值被忽略，仍按优先级采用其它合法控制；没有合法控制可生效时本轮按关闭处理、不回退面板。合法 enabled:false 短路先于 effort 校验，本次不新增 400。`reasoning.exclude` 与顶层 `include_reasoning` 不纳入统一解析，各路径行为保持；详见 [reasoning contract](reasoning-effort.md)。

### English: 2.0 MCP access controls

This integration branch enables MCP transport access controls for 2.0. Configure exact Host values (case and port included, or host:*) in MCP_ALLOWED_HOSTS. Literal IP access without registration applies to non-browser clients without an Origin header, and to browser pages hosted on the built-in local origins (localhost / 127.0.0.1 / [::1], on any port); other browser origins must still be registered in MCP_ALLOWED_ORIGINS. These checks are not authentication for the public admin or data APIs.

Compose: add the Host entry to the host .env, add MCP_ALLOWED_ORIGINS for browser clients, then run `docker compose up -d --build`. Native Python users export the variables before starting. Zeabur may reference `${ZEABUR_WEB_DOMAIN}`; verify expansion after deployment. Update temporary domain entries when they change. A tunnel's httpHostHeader can rewrite the effective Host. Shared hosting suffixes are not trusted globally; Quick Tunnel does not support SSE.

Stable errors are 421 mcp_host_not_allowed, 403 mcp_origin_not_allowed and 400 invalid_content_type; no header values are returned. Uppercase APPLICATION/JSON passes security validation but receives SDK protocol HTTP 415. Requests are limited to 4 MiB by the SDK. The nine-key status endpoint reports counts, flags and a throttled observation timestamp only. MCP_AUTH_TOKEN was unused and removed in SEC-01a. The upgrade gate remains false until RELEASE-01; since SEC-01b (#84), GET / POST / DELETE on `/calendar/mcp` reach MCP just like `/memory/mcp`; `/memory` no longer redirects.

### English: 2.0 reasoning effort

Kiwi no longer enables thinking by default in 2.0. When neither a non-null `reasoning_effort` nor a non-null `reasoning` object is supplied, the gateway uses the panel setting (off by default). Clients relying on the previous implicit enablement should send an explicit effort or select a panel value. Upstream models may still reason by default. Direct Anthropic requests no longer have temperature changed to 1 due to implicit gateway enablement.

`reasoning_effort` also accepts `none` (off) and `minimal` (lossily mapped to low). A `reasoning` object supports `enabled:false`, `effort` including aliases, or a nonnegative integer `max_tokens` (zero means off; positive values use budget floors). Values below 5000 still map to low (budget 5000), so this is not an exact budget cap. A valid explicit string wins; null is absent. Off omits gateway reasoning controls and cannot guarantee that the model stops reasoning. Empty/all-null/unknown-only objects use the panel. Invalid enabled/max_tokens values are ignored while other valid controls retain their priority; with no valid control to apply, invalid controls resolve to off without panel fallback. Valid enabled:false short-circuits effort validation; this change adds no rejection shapes. `reasoning.exclude` and top-level `include_reasoning` keep their existing path-specific behavior. See [the reasoning contract](reasoning-effort.md).

### 2.0 嵌入换尺子 / Embedding identity upgrade

旧向量没有可信模型身份，升级后标记 `unknown`，不参与新身份的语义比较。请在供应商页默认嵌入模型旁「向量对齐」重新检查并确认重建；**重建会产生嵌入模型费用**。新记忆与缺向量自动回填也可能产生少量费用，旧 profile 不自动重建。任务展示成功、失败、跳过数；中断后等两分钟租约过期可继续。`GET /admin/migrate-embeddings` 已停用，返回 410。

Anthropic 格式不用于嵌入。中转站使用 `openai` 格式仍可能选到不支持嵌入的 Claude 等渠道，`api_format` 无法证明模型能力，「测试嵌入」的真实请求才是可靠判法。保存默认嵌入模型会自动发送一次短探针，另有手动测试按钮；测试可能计费。保存成功而测试失败时，设置已经保存，请依据受控诊断检查端点、Key、模型与供应商状态。

Existing vectors become `unknown` and are excluded from new-profile semantic comparisons. Explicitly rebuild beside the default embedding model; **rebuilding incurs embedding-provider charges**. Routine generation/backfill can also cost money. Old profiles are never rebuilt automatically. Interrupted jobs resume after lease expiry (two minutes). The previous GET migration endpoint returns 410. Native Anthropic format is unsuitable for this request; an OpenAI-format relay can still select an unsupported model, so use the actual probe. Default-model saves trigger a short, potentially billable test. A failed test does not undo a successful settings save. See [mechanism and limits](embedding-versioning.md).

### 2.0 聊天抽屉项目范围 / Chat-drawer scope (W2-05b)

自建前端的项目聊天：抽屉保存落本项目，全局最近记忆只列全局，锁定/解锁与数量遵循可见集合（全局；或全局＋本项目），用户锁不被自动退休；第三方客户端无项目概念时公共 MCP 接口保持原行为。Project-aware chat drawers now save into the project, restrict global recent results to global memories, and scope locks and counts to the visible collection; public MCP clients without project context retain their existing behavior. 集成分支待验收、未发布。

### 2.0 错误出口稳定形 / Stable error boundaries (ERR-01)

错误是客户端可依赖的协议。枚举的50个普通HTTP异常出口、客户端解码错误和三处输入错误统一返回 `{"error":"<code>","error_code":"<code>"}`；日志仅记受控事件与白名单码。脚本应按HTTP状态和 `error_code` 判断，停止解析异常原文。24个原HTTP 200错误端点现在按来源返回400（输入）、404（不存在）、500（内部）、502（上游）；原500出口的超时/上游错误现在为502：

- `GET /debug/memories`
- `DELETE /debug/memories/{memory_id}`
- `POST /debug/memories/batch-delete`
- `POST /debug/memories/batch-update`
- `DELETE /debug/memories`
- `GET /debug/memory-heat`
- `POST /debug/memories/{memory_id}/toggle-permanent`
- `GET /calendar/{date}`
- `GET /calendar`
- `PUT /admin/calendar/{date}`
- `DELETE /admin/calendar/{date}`
- `POST /comments`
- `GET /comments`
- `DELETE /comments/{comment_id}`
- `GET /dream/scenes`
- `DELETE /admin/dream/{dream_id}`
- `GET /admin/default-prompts`
- `POST /admin/restore-prompt/{key}`
- `GET /admin/categories`
- `POST /admin/categories`
- `PUT /admin/categories/{category_id}`
- `DELETE /admin/categories/{category_id}`
- `GET /admin/system-prompt`
- `PUT /admin/system-prompt`

客户端坏JSON或非UTF-8体/备份JSON成员现在返回400 `invalid_request`，替代原500/502/固定中文。`/debug/memories` DELETE、`/admin/extract-now`、`/dream/start`、`/dream/start-detached` 的空体及纯空白体仍按空对象；非空坏体返回400。reset需要body，解码错误400；确认码错误固定中文、其它失败“重置失败”保持。可选体的非对象JSON：clear保留原确认错误，其余按空对象；其它入口的非对象处理不在本票统一。

供应商空名称、空搜索query、非ZIP文件改400 `invalid_request`。后台任务枚举失败字典增加 `error_code`，其余字段及日页面三元组保留；使用 public_model_result 的管理接口按码返回状态，不再恒502。未知stable_error码规范为500 `internal_error`。

保留合同：X1 reasoning_effort错误仍为OpenAI兼容嵌套对象，param/合法档位保留，但字符串输入值不回显；W2导入/删除/重置失败及invalid_project_id、sources_changed五处保持；记忆未启用仍200单键；周/月/周期总结的 `model returned invalid format` 字典不变；embedding-probe诊断仍200。面板已兼容，无需改版。

**English.** The 50 enumerated ordinary HTTP exception exits, client decoding failures and three input errors now use the two-field `error`/`error_code` envelope. Update scripts to read the status and code, rather than raw exception text. The 24 routes above formerly returned error bodies with HTTP 200; status now follows input (400), missing resource (404), internal failure (500), or upstream failure (502). Previously-500 paths return 502 for upstream failures/timeouts. Unknown stable_error codes normalize to HTTP 500/internal_error.

Malformed JSON and non-UTF-8 request/backup-member bytes return 400/invalid_request. The four optional-body routes listed above preserve empty/whitespace bodies as `{}`; malformed nonempty bodies fail. Reset requires a body, while its fixed confirmation and generic failure responses remain intact. Non-object JSON is otherwise not standardized here. Empty provider names/search queries and non-ZIP uploads use the same 400 envelope. Enumerated background failure dictionaries gain error_code, preserving other fields and the day-page tuple; admin model-result endpoints map status by code.

Exceptions remain explicit: the reasoning_effort nested error shape and allowed choices (without echoing input), five W2 fixed responses, HTTP-200 memory-disabled response, three calendar `model returned invalid format` dictionaries, and HTTP-200 embedding diagnostics. No new authentication, error codes, or panel changes are introduced.

### 2.0 用户锁 / User locks

Dream 不再改写用户手动锁定的记忆；promote 只允许全局非用户锁行。退休 UPDATE 重核永久状态与锁来源，按实际更新行统计，不回溯修改历史行。

Dream promotion preserves user locks and only promotes eligible global rows. Retirement atomically rechecks lock state/source and reports actual updates. Historical rows are not migrated.
