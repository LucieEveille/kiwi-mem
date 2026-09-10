# MCP transport security / MCP 传输安全

BUILD-01 在 2.0 集成分支启用，发布前按 UPGRADING 配置。只包装 MCP 子应用，不为 /v1、/admin、/sync 增加全站 Host 校验。公版仍无登录认证，部署方负责访问边界。

## 配置与执行

MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS 只来自进程环境，逗号分隔、去空项、非法项忽略计数、合法项去重保序；不从请求头或 CORS 配置学习。内置 Host 六项：localhost、localhost:*、127.0.0.1、127.0.0.1:*、[::1]、[::1]:*；Origin 六项为对应 http:// 前缀。SDK 的 :* 只匹配带端口形态，故裸项与端口项必须成对。

名单惰性构造一次。两个 FastMCP 构造器与 guard 接收同一缓存对象；SDK 从构造输入重建等值副本并按引用交给 session manager 与每个 transport 的 TransportSecurityMiddleware。副本不受我方对象后续写入影响；升 mcp 时重核“副本还是引用”。守卫同时检查构造参数 identity、两个副本完整内容、三个对象请求前后不变，不回绑 SDK 内部状态。

包装顺序为 observe(guard(SDK))。观察层只记 foreign 标记和时间；门卫先验证 POST Content-Type，再验证恰一个合法 Host，再验证 Origin。拒绝使用固定 JSON 与事件码，不回显地址。SDK logger 的幂等窄 filter 将五类拒绝 warning 改成固定 reason，不屏蔽其他记录或改变级别。

## IP 与两层差异

严格 ipaddress 解析的 IP Host 经 Origin / Content-Type 检查后，只在 scope 副本中将 Host 改成 127.0.0.1，其他字段及原 scope 不动；非 IP scope 原样传 SDK。mcp 1.29.1 流式 HTTP 除安全层外不消费 Host，升 mcp 时须重核，不能推广到其他协议或任意中间件。

相对于 SDK 安全层有两类明确差异：(a) 合法 IP 字面量被门卫接纳，经局部改写通过 SDK；(b) 多 Host 或结构畸形但碰巧命中 base:* 的 Host 被门卫拒绝。其余安全检查跟随 SDK：Content-Type 仅 lower、不 strip；Origin 缺失允许，存在则精确或 base:* 前缀匹配。Content-Type 还有第三层——SDK 传输层要求 application/json 精确小写（可带 ; charset=…），大小写异常回 415，属协议层，门卫不复制。

DNS 重绑定通过域名访问本机服务，因此域名仍须登记；带跨站 Origin 的 IP 请求仍拒绝，表单类型 POST 仍拒绝。无 Origin 的非浏览器请求不属于这条浏览器防线。IP 放行论证仍须通过独立 CC 对抗；有反例按裁决回退为精确 IP 登记，不把 Host 校验描述成认证。

## 诊断与边界

状态口九键、启动计数摘要、固定 mcp_access_rejected reason 与 SDK mcp_transport_security_rejected reason 供诊断，无原始头值。421 登记 Host、403 登记 Origin、400 修 Content-Type，具体操作见 UPGRADING。4 MiB 请求体上限由 SDK 实现。

不内置 zeabur.app / trycloudflare.com 等共享后缀，不做面板配置，不适配 Quick Tunnel 流式。calendar 子实例受保护，但 /calendar/mcp 外部路由归 SEC-01b。版本号和升级 gate 由 RELEASE-01 更新。
