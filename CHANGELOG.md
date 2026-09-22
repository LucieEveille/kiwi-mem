# Changelog

## Unreleased — 2.0.0 integration / KIWI-LOCK-01

- Dream 不再改写用户手动锁定的记忆；promote 只允许全局非用户锁行。退休 UPDATE 重核永久状态与锁来源，按实际更新行统计，不回溯修改历史行。
- Dream promotion preserves user locks and only promotes eligible global rows. Retirement atomically rechecks lock state/source and reports actual updates. Historical rows are not migrated. Pending acceptance and release.

## Unreleased — 2.0.0 integration / W2-05b (#90)

- 聊天抽屉五个记忆工具接入私有 scope 执行器：全局只看全局，项目看全局＋本项目，保存落当前层，锁定/解锁及总数均遵循可见集合；用户锁原子写入 `lock_source='user'`，但 Dream promote 仍可能改写来源并使该锁在满足退休条件后失效，见 [KIWI-LOCK-01 继承债](KNOWN_ISSUES.md#kiwi-lock-01)。
- Chat-drawer memory tools now use the conversation scope directly, without debug HTTP loopback. Public MCP schemas/endpoints, debug handlers and quarantine remain unchanged. See [scope behavior](docs/event-ledger-scope-and-reconciliation.md#chat-drawer-memory-scope-w2-05b) and [upgrading](docs/UPGRADING.md). Pending acceptance and release.

## 1.7.0 — Unreleased (2026-09)

- 修补 FastAPI / Starlette 依赖，保留 MCP、httpx、uvicorn 基线。
- MCP 登记预告、无地址值的观察数据和只读状态口；不改变访问行为。
- 更新脚本增加配置预检、带状态续跑与有界 MCP initialize 健康探针。
- 修复升级时覆写操作员 `PORT` 的回归；统一 Python / jq / 无助手的端口取值与引号、BOM 处理，探针内部使用 `LISTEN_PORT`。
- Starlette 静态资源支持 Range（206 / 416 / `Accept-Ranges`）；属于 HTTP 行为变化，访问控制保持原样。The dependency upgrade enables static-file Range responses without introducing access controls.
- 部署配置透传与 [升级预告](docs/UPGRADING.md)。

限时风险例外：1.7.0 暂留 `mcp==1.12.4`，其三条公告 CVE-2025-66416 / CVE-2026-52869 / CVE-2026-59950 仍在。理由：升 mcp ≥ 1.23 会让 SDK 对本机 host 自动开启 Host / Origin 保护、远程 MCP 在准备版就被拒，违背“先提醒再改规则”。解除条件：KIWI-BUILD-01 合入 `release/kiwi-sync` 并随 2.0.0 发布。负责票：BUILD-01。本例外不豁免其他任何扫描结果。


## Unreleased — 2.0.0 integration / KIWI-BUILD-01

MCP 接入 Host / Origin / Content-Type 保护与不回显头值的稳定错误；IP 客户端仍需满足 Origin 规则。升级 mcp 1.29.1、httpx 0.27.2、uvicorn 0.31.1，Python 基础镜像改 ECR 源。详见 docs/UPGRADING.md。当前版本标识仍 1.7.0，最终版本与升级 gate 由 RELEASE-01 同批更新。

MCP transport access controls are enabled on the integration branch, with stable header-free errors and the updated dependency pins. See the upgrade guide before deploying 2.0.

## Unreleased — 2.0.0 integration / KIWI-SEC-01b (#84)

- 两条 MCP 精确路由前置，修复 calendar GET 被业务路由截走及 IP 尾斜杠重定向丢端口；连接 URL 保持不变。
- 行为变更：`/calendar/{date}` 非 GET 由 404 改 405；`/memory` 不再重定向；非端点路径不再经门卫或写观察记录。
- Exact MCP routes now precede business routes. Calendar GET reaches MCP, trailing-slash redirects retain the original port, and non-endpoint paths bypass observation and the guard. Date-path non-GET requests return 405 instead of 404. These changes are on the integration branch, not yet released.

## Unreleased — 2.0.0 integration / KIWI-THINK-01 (#86)

- 行为变更：网关缺省不再主动开启思考；面板思考强度开始生效；新增两条日志事件；面板下拉文案更新（档位不变）。优先级为显式 ＞ 面板 ＞ off。
- Omitted effort now uses the panel setting, including its factory default off. Kiwi no longer implicitly enables reasoning; upstream model defaults remain outside this guarantee. Explicit effort, endpoint downgrades and Anthropic budget limits are unchanged. See [reasoning effort](docs/reasoning-effort.md).

## Unreleased — KIWI-EMB-01

- Add model/route/text identity to memory, scene and file vectors; isolate incompatible vectors and validate batch indices.
- Add durable, lease-owned vector alignment with explicit cost confirmation, failure counts and interruption recovery; retire GET migration (410).
- Add a bounded, redacted embedding probe and a model-adjacent panel with automatic post-save testing, manual diagnostics and stale-response protection.
- Preserve the existing embedding statistics fields and keyword fallback. Upgrade requires explicit alignment of old unknown vectors; provider charges may apply.

### Unreleased — ERR-01

- Normalize enumerated HTTP/input and background failure results to stable error codes; preserve optional empty bodies and existing W2/calendar/probe contracts.
- Remove reasoning_effort input echoes, bound background logs and HTTP/1.1 DEBUG reason phrases; add AST, behavioral and mutation guards. See docs/UPGRADING.md for script compatibility changes.
