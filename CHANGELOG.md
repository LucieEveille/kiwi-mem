# Changelog

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
