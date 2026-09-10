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
