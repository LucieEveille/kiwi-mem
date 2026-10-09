# Client compatibility / 客户端兼容性

## 显式输出上限与 stop / Explicit output limits and stop

Kiwi 在普通转发与工具循环、OpenAI 与 Anthropic 四条路径上保留或转换客户端显式给出的 `max_tokens` / `max_completion_tokens` 与 `stop`：OpenAI 出站保留客户端原上限键名；`stop` 在普通转发保持客户端原形状，在工具循环规范化为字符串数组；Anthropic 出站转为 `max_tokens` / `stop_sequences`，工具循环每轮请求都带上。两种上限同时合法时 `max_tokens` 优先；`null` 视为未提供。上限须为正整数（布尔值不算整数），`stop` 须为非空字符串或 1～4 个非空字符串的数组；任一非空字段非法时，入口返回固定文案的 400，尚未发送上游请求。

具体模型是否支持这些参数由上游决定。例如 OpenAI o 系对 `max_tokens` 有兼容限制，o3 / o4-mini 不支持 `stop`；`max_completion_tokens` 包含思考 token，不能理解为纯可见回答长度。工具循环中的上限是每次模型请求的上限，不是整个多轮流程的累计上限。参见 [OpenAI Chat Completions 参数说明](https://platform.openai.com/docs/api-reference/chat/create)。

Kiwi preserves or translates explicit `max_tokens`, `max_completion_tokens`, and `stop` across ordinary forwarding and tool loops with either OpenAI or Anthropic output. OpenAI output retains the client's limit key; ordinary forwarding preserves the original non-null `stop` shape, while tool loops normalize it to a string array. Anthropic output uses `max_tokens` and `stop_sequences`; every tool-loop model request carries these controls. When both limits are valid, `max_tokens` wins. Null means omitted. Limits must be positive integers, excluding booleans; stop must be a nonempty string or an array of one to four nonempty strings. Invalid non-null controls receive a fixed-message 400 before an upstream request is sent.

Forwarding does not guarantee model support. OpenAI o-series models have compatibility restrictions on `max_tokens`; o3 / o4-mini do not support `stop`, and `max_completion_tokens` includes reasoning tokens. A tool-loop limit applies to each model request, not to the aggregate of the entire loop. See the [upstream parameter reference](https://platform.openai.com/docs/api-reference/chat/create).

## 私有事件帧 / Private event frames

Kiwi 在 `/v1/chat/completions` 流中穿插五种自家事件帧：`ev_session` 会话身份回传、`ev_handoff` 换窗提示、`ev_tool` 工具事件、`ev_memory` 记忆保存结果、`ev_dream` Dream 触发。自 2.0 起，每帧均带空的 `choices: []`，严格按 OpenAI chunk 形状解析的客户端会将其作为零个 choice 的 chunk，不产正文、不报错。若私有帧是流的第一帧（服务端生成会话身份、换窗、预置工具事件），Vercel AI SDK 系客户端的响应元数据 `id / model / created` 会为空且不回填，正文与结束不受影响。不消费这些事件的客户端无需处理；事件语义与 `[DONE]` 位置不变，错误帧仍为 `{"error", "error_code"}` 两键（ERR-01 冻结合同）。`ev_session` 只在启用 `session_identity_v2_enabled` 且服务端生成会话身份时出现，该设置默认关闭。

Kiwi interleaves five private events in `/v1/chat/completions` streams: `ev_session` returns a session identity, `ev_handoff` signals a conversation handoff, `ev_tool` reports tool events, `ev_memory` reports memory-save results, and `ev_dream` signals a Dream trigger. From 2.0, each carries empty `choices: []`, so strict OpenAI chunk parsers accept it as a zero-choice chunk without producing text or an error. When a private event is the first stream frame (a server-generated session identity, handoff, or preset tool event), Vercel AI SDK clients receive empty response metadata (`id / model / created`) with no later backfill; text and stream completion are unaffected. Clients that do not consume these events need no special handling. Event semantics and the position of `[DONE]` are unchanged; error frames retain exactly the `error` and `error_code` keys under the frozen ERR-01 contract. `ev_session` appears only when `session_identity_v2_enabled` is enabled and the server generates the session identity; this setting is off by default.

## 会话识别 / Session identity

Kiwi 依次采用非空 body `conversation_id`、`X-Conversation-Id`（Kelivo）、`X-Session-ID`（RikkaHub）、`X-OpenWebUI-Chat-Id`，最后沿用既有 v2 随机身份或首句哈希回退。HTTP 头名不区分大小写；每种头取按接收顺序首个有效值：去除首尾空白后，长度为 1～200 字符且全部可打印。空值、超长与控制字符值跳过。头身份为 `hdr-<cid|sid|owc>-<sha256 前 24 位>`，不同来源各自隔离；日志只记来源与计数，不记原值或哈希。头来源不查询 Chat 会话 metadata，但显式项目仍须数据库验证；body 中同名的 `hdr-*` 字符串仍走 body 身份规则。头来源身份不通过 `X-Kiwi-Session-Id` 或 `ev_session` 回显。

Kelivo / RikkaHub 的已核 OpenAI 请求链默认带各自会话头。Open WebUI 的内建转发默认关闭，需显式配置：可在连接的 Headers 中填 `{"X-OpenWebUI-Chat-Id":"{{CHAT_ID}}"}`，无需连带开启用户信息头转发。Chatbox / Cherry Studio / LibreChat 的已核自定义 OpenAI 路径没有自动会话头；LibreChat 可选用会话变量模板，没有有效头时仍走原回退。稳定会话不等于项目隔离或自动换窗；同一会话头也可能被标题等任务复用，不能据此识别任务。

Kiwi selects a nonempty body `conversation_id`, then `X-Conversation-Id`, `X-Session-ID`, then `X-OpenWebUI-Chat-Id`, before the existing v2/random or first-message-hash fallback. Header names are case-insensitive. Within each name, the first valid received value wins: trim whitespace, require 1–200 printable characters, and skip invalid values. Header identities use `hdr-<cid|sid|owc>-<first 24 SHA-256 hex digits>` with separate source namespaces. Logs contain only the source and count. Header identities skip Chat conversation metadata lookup; explicit projects still require database verification. A body-supplied `hdr-*` string retains body identity behavior. Header identities are not echoed through response headers or `ev_session`.

The inspected Kelivo and RikkaHub OpenAI paths send their session headers by default. Open WebUI requires explicit forwarding; its connection Headers can use `{"X-OpenWebUI-Chat-Id":"{{CHAT_ID}}"}` without forwarding user information. The inspected custom OpenAI paths in Chatbox, Cherry Studio, and LibreChat do not automatically send these headers; LibreChat can optionally use a conversation-variable template. Missing valid headers retain the existing fallback. Stable sessions do not provide project isolation or automatic handoff, and task requests may reuse a conversation header.

## 后台任务信号 / Background task signal

启用 `task_signal_enabled` 时，有效的 `X-Kiwi-Task` 明确表示本次请求旁路 Kiwi 的人设与记忆注入、客户端 system 模板替换、换窗注入、落账、提取、强制搜索、网关工具收集和 Dream 检测。去首尾空白后长度须为 1～64 字符且全部可打印；重复头取首个有效值，空值与非法值忽略，不按任务名称或消息形状猜测。客户端自己的 messages / tools 保留，思考与输出上限、stop、协议转换、错误帧等原有处理继续执行。任务身份不持久化也不回显；内部 `task-*` 临时键仍可按既有 OpenRouter 粘性路由送往上游，不能理解为上游绝不收到身份字段。

**固定非空任务头只配置在任务专用的供应商、模型或 endpoint 条目。** 给普通聊天共用条目填固定任务头，会使正常对话也旁路记忆和落账。以下是 2026-10-04 固定源码调查得到的配置草稿，仍需客户端真机验收：

| 客户端 | 任务配置与限制 |
| --- | --- |
| Kelivo | 建任务专用 provider，在自定义 HTTP 头填 `X-Kiwi-Task: background`，将辅助模型指向它；聊天继续用原 provider。也可将任务模型直接指向非 Kiwi 供应商。 |
| RikkaHub | 为标题、追问与压缩选择任务专用模型，在该模型高级设置加 `X-Kiwi-Task: background`。已核翻译链不复制模型自定义头，翻译应另选非 Kiwi 供应商。 |
| Cherry Studio | 建任务专用 provider，其 Headers JSON 填 `{"X-Kiwi-Task":"auxiliary"}`；quick / 翻译等任务选择该条目，普通聊天勿选它。 |
| Open WebUI | 共用连接可使用动态模板 `{"X-Kiwi-Task":"{{TASK}}","X-OpenWebUI-Chat-Id":"{{CHAT_ID}}"}`：普通请求的 TASK 为空，任务请求非空。**MoA 回答合并也有非空 TASK，用户可见合并答案也会旁路落账**；选择其它连接/分流方案，或明确接受该边界。只改统一任务模型不能覆盖 MoA。 |
| LibreChat | 建任务专用 custom endpoint alias，headers 填 `X-Kiwi-Task: background`，标题的 `titleEndpoint` 或摘要 provider 指向它。管理员须配置固定 `baseURL`；`user_provided` 路径会抑制管理员 headers，不能套用此方案。活动等其它辅助任务需分别检查。 |
| Chatbox | 已核自定义 OpenAI 路径没有可配置任意头的用户设置，不提供加头教程。标题可另选非 Kiwi provider；摘要的远程 fastModel 默认与设置入口未核实，不能承诺改标题配置就覆盖摘要。 |

无法加头且无法分流的任务仍按普通聊天处理；只有一条 user 消息、缺历史、与旧会话共用头，都不作为自动旁路判据。`session_header_identity_enabled` 与 `task_signal_enabled` 均为站点开关，默认开启，可在管理面板「兼容与回退」关闭；它们不参加客户端设置同步。

With `task_signal_enabled` on, a valid `X-Kiwi-Task` explicitly bypasses Kiwi persona/memory injection, client system-template substitution, handoff injection, ledger recording, extraction, forced search, gateway tool collection, and Dream detection. Values must contain 1–64 printable characters after trimming; the first valid duplicate wins. Empty/invalid values are ignored, without guessing from task names or message shapes. Client messages/tools and existing reasoning, output-limit, stop, protocol conversion, and error handling remain active. Task identity is neither persisted nor echoed; the internal temporary `task-*` key can still reach upstream via existing OpenRouter sticky routing.

**A fixed nonempty task header belongs only on a task-specific provider/model/endpoint**, never a shared chat entry. Kelivo can use a dedicated provider's custom headers; RikkaHub title/suggestion/compression models can use advanced model headers, while its inspected translation path needs a non-Kiwi provider. Cherry Studio supports provider Headers JSON. Open WebUI may share the dynamic `{{TASK}}` / `{{CHAT_ID}}` template above, but MoA merged answers also carry TASK and will bypass recording; changing the common task model does not cover MoA. LibreChat needs a dedicated alias with an administrator-fixed `baseURL`; `user_provided` suppresses administrator headers. Chatbox has no verified custom-header UI on this path: route title generation to a non-Kiwi provider, without assuming that also reroutes summary generation. These source-based configuration drafts require real-client validation. Tasks without a signal or separate route remain ordinary chats. Both site switches default on, can be disabled under Compatibility and fallback, and are excluded from client settings sync.

The broader client matrices will be incorporated with RELEASE-01.
