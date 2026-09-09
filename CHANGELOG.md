# Changelog

## 1.7.0 — Unreleased (2026-09)

- 修补 FastAPI / Starlette 依赖，保留 MCP、httpx、uvicorn 基线。
- MCP 登记预告、无地址值的观察数据和只读状态口；不改变访问行为。
- 更新脚本增加配置预检、带状态续跑与有界 MCP initialize 健康探针。
- 部署配置透传与 [升级预告](docs/UPGRADING.md)。

限时风险例外：1.7.0 暂留 `mcp==1.12.4`，其三条公告 CVE-2025-66416 / CVE-2026-52869 / CVE-2026-59950 仍在。理由：升 mcp ≥ 1.23 会让 SDK 对本机 host 自动开启 Host / Origin 保护、远程 MCP 在准备版就被拒，违背“先提醒再改规则”。解除条件：KIWI-BUILD-01 合入 `release/kiwi-sync` 并随 2.0.0 发布。负责票：BUILD-01。本例外不豁免其他任何扫描结果。
