# MCP transport security / MCP 传输安全

BUILD-01 在 2.0 集成分支启用，发布前按 UPGRADING 配置。只包装 MCP 子应用，不为 /v1、/admin、/sync 增加全站 Host 校验。公版仍无登录认证，部署方负责访问边界。

## 配置与执行

MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS 只来自进程环境，逗号分隔、去空项、非法项忽略计数、合法项去重保序；不从请求头或 CORS 配置学习。内置 Host 六项：localhost、localhost:*、127.0.0.1、127.0.0.1:*、[::1]、[::1]:*；Origin 六项为对应 http:// 前缀。SDK 的 :* 只匹配带端口形态，故裸项与端口项必须成对。

名单惰性构造一次。两个 FastMCP 构造器与 guard 接收同一缓存对象；SDK 从构造输入重建等值副本并按引用交给 session manager 与每个 transport 的 TransportSecurityMiddleware。副本不受我方对象后续写入影响；升 mcp 时重核“副本还是引用”。守卫同时检查构造参数 identity、两个副本完整内容、三个对象请求前后不变，不回绑 SDK 内部状态。

包装顺序为 observe(guard(SDK))。观察层只记 foreign 标记和时间；门卫先验证 POST Content-Type，再验证恰一个合法 Host，再验证 Origin。拒绝使用固定 JSON 与事件码，不回显地址。SDK logger 的幂等窄 filter 将五类拒绝 warning 改成固定 reason，不屏蔽其他记录或改变级别。

## IP 与两层差异

严格 ipaddress 解析的 IP Host 经 Origin / Content-Type 检查后，只在 scope 副本中将 Host 改成 127.0.0.1，其他字段及原 scope 不动；非 IP scope 原样传 SDK。mcp 1.29.1 流式 HTTP 除安全层外不消费 Host，升 mcp 时须重核，不能推广到其他协议或任意中间件。

相对于 SDK 安全层有三类明确差异：(a) 合法 IP 字面量被门卫接纳，经局部改写通过 SDK；(b) 多 Host 或结构畸形但碰巧命中 base:* 的 Host 被门卫拒绝；(c) 空值 `Origin:` 头：门卫 403，SDK 视同缺失放行。其余安全检查跟随 SDK：Content-Type 仅 lower、不 strip；Origin 缺失允许，存在则精确或 base:* 前缀匹配。Content-Type 还有第三层——SDK 传输层要求 application/json 精确小写（可带 ; charset=…），大小写异常回 415，属协议层，门卫不复制。

DNS 重绑定通过域名访问本机服务，因此域名仍须登记；带跨站 Origin 的 IP 请求仍拒绝，表单类型 POST 仍拒绝。无 Origin 的非浏览器请求不属于这条浏览器防线。IP 放行论证仍须通过独立 CC 对抗；有反例按裁决回退为精确 IP 登记，不把 Host 校验描述成认证。

## 诊断与边界

状态口九键、启动计数摘要、固定 mcp_access_rejected reason 与 SDK mcp_transport_security_rejected reason 供诊断，无原始头值。421 登记 Host、403 登记 Origin、400 修 Content-Type，具体操作见 UPGRADING。4 MiB 请求体上限由 SDK 实现。

不内置 zeabur.app / trycloudflare.com 等共享后缀，不做面板配置，不适配 Quick Tunnel 流式。两个 MCP 的外部精确路由见下一节。版本号和升级 gate 由 RELEASE-01 更新。

## 挂载与路径 / Mounting and paths

SEC-01b（PR #84）将 `/memory/mcp` 与 `/calendar/mcp` 注册为精确路由，排在全部业务路由之前。每条端点按 `AsgiEndpoint(observe(guard(SDK)))` 派发，calendar 的 GET 不再进入 `/calendar/{date}`。POST 在旧版已经可达，本次同时恢复 GET 通道。

| 路径 / Path | GET | POST initialize | DELETE |
|---|---|---|---|
| `/memory/mcp` | Accept 含 SSE：200 `text/event-stream`；仅 JSON：406 | 200，Memory Garden，6 tools | SDK 405，JSON-RPC `error.code=-32600` |
| `/calendar/mcp` | 同上 / Same as memory | 200，Calendar & Dream，11 tools | SDK 405，JSON-RPC `error.code=-32600` |
| `/memory/mcp/`、`/calendar/mcp/` | 307，Location 保留原 Host 与端口 | 同左 / Same redirect | 同左 / Same redirect |
| `/memory`、`/memory/` | 404，无重定向 | 404 | 404 |
| `/memory/mcp/extra`、`/calendar/mcp/extra` | 404 | 404 | 404 |
| `/calendar` | 原业务 200 / Existing business response | 405 | 405 |
| `/calendar/{date}` | 原业务 200 / Existing business response | 405（原 404 / previously 404） | 405（原 404 / previously 404） |

精确端点上的外来 Host 仍回 421，未登记 Origin 仍回 403，POST Content-Type 仍先经门卫检查。尾斜杠由外层 FastAPI 在进入门卫前返回 307，Location 使用请求原 Host:port；不另注册斜杠端点。`/memory/extra` 等非端点路径直接 404，不经门卫、不写观察、不记拒绝日志；观察范围因此收窄到两个精确端点。GET SSE 在 stateless 模式下可以是持续空流，健康检查应使用有界 POST initialize。

Both exact routes precede all business routes and retain observation → access guard → SDK. Calendar POST already worked before this change; its GET now reaches MCP too. Slash redirects happen in the outer FastAPI router before Host rewriting, preserving the original Host and port. Non-endpoint paths return 404 without observation writes or guard rejection logs. Calendar business GET responses are unchanged; non-GET date requests now return 405 instead of 404. Foreign Hosts and unregistered Origins remain rejected on both exact endpoints. Stateless GET SSE may remain open without events; use a bounded initialize POST for health checks.

端点工厂先调用 `streamable_http_app()` 初始化惰性 session manager，再直接代理其 `handle_request`。原三个子应用工厂保留兼容；主 lifespan 仍启动两个 manager。SDK 的请求体限制和 transport security 仍在派发链内。升级 mcp 时需重核 handle_request 签名及路径依赖。Factories warm up each lazy manager before main's lifespan and delegate to handle_request; the existing app factories remain available. Recheck this SDK boundary on dependency upgrades.
