# Client compatibility / 客户端兼容性

## 显式输出上限与 stop / Explicit output limits and stop

Kiwi 在普通转发与工具循环、OpenAI 与 Anthropic 四条路径上保留或转换客户端显式给出的 `max_tokens` / `max_completion_tokens` 与 `stop`：OpenAI 出站保留客户端原上限键名；`stop` 在普通转发保持客户端原形状，在工具循环规范化为字符串数组；Anthropic 出站转为 `max_tokens` / `stop_sequences`，工具循环每轮请求都带上。两种上限同时合法时 `max_tokens` 优先；`null` 视为未提供。上限须为正整数（布尔值不算整数），`stop` 须为非空字符串或 1～4 个非空字符串的数组；任一非空字段非法时，入口返回固定文案的 400，尚未发送上游请求。

具体模型是否支持这些参数由上游决定。例如 OpenAI o 系对 `max_tokens` 有兼容限制，o3 / o4-mini 不支持 `stop`；`max_completion_tokens` 包含思考 token，不能理解为纯可见回答长度。工具循环中的上限是每次模型请求的上限，不是整个多轮流程的累计上限。参见 [OpenAI Chat Completions 参数说明](https://platform.openai.com/docs/api-reference/chat/create)。

Kiwi preserves or translates explicit `max_tokens`, `max_completion_tokens`, and `stop` across ordinary forwarding and tool loops with either OpenAI or Anthropic output. OpenAI output retains the client's limit key; ordinary forwarding preserves the original non-null `stop` shape, while tool loops normalize it to a string array. Anthropic output uses `max_tokens` and `stop_sequences`; every tool-loop model request carries these controls. When both limits are valid, `max_tokens` wins. Null means omitted. Limits must be positive integers, excluding booleans; stop must be a nonempty string or an array of one to four nonempty strings. Invalid non-null controls receive a fixed-message 400 before an upstream request is sent.

Forwarding does not guarantee model support. OpenAI o-series models have compatibility restrictions on `max_tokens`; o3 / o4-mini do not support `stop`, and `max_completion_tokens` includes reasoning tokens. A tool-loop limit applies to each model request, not to the aggregate of the entire loop. See the [upstream parameter reference](https://platform.openai.com/docs/api-reference/chat/create).

The broader client matrices will be incorporated with RELEASE-01.
