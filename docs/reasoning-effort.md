# 思考强度 / Reasoning effort

KIWI-THINK-01（PR #86）用于 2.0 集成分支。用户应能决定是否让网关开启思考，而不是因为客户端省略参数就被网关隐式开启。入口每请求解析一次，普通转发与工具循环共享结果。

## 优先级与边界 / Precedence and scope

**显式 ＞ 面板 ＞ off**：请求 `reasoning_effort` 显式合法值优先；缺席或 null 时读取面板同名配置。配置系统返回出厂默认 off 也算配置来源；空、None 或非法配置防御兜底为 off。请求非法值仍返回原有 400 invalid_value，大小写与首尾空格规范化不变。

`off` 表示网关不主动开启：删除 `reasoning` / `reasoning_effort` 后不添加开启参数。它不保证上游模型自身不推理或不收费；强制关闭与模型能力归后续专项票。`exclude` 隐藏推理内容而不关闭推理。内部 `skip_system_prompt` 请求不主动开启思考，无论面板如何设置。

The precedence is explicit request > panel configuration > off. A missing or null request field reads configuration once; valid explicit input wins without reading the panel. The configuration getter includes the factory default. Empty or invalid configuration falls back to off. Invalid explicit input retains the existing HTTP 400 contract.

Off means Kiwi does not actively enable reasoning, not that upstream reasoning is forcibly disabled. Model defaults and mandatory reasoning can still apply. Internal skip-system-prompt requests do not enable reasoning. The gateway does not send provider-specific disable controls in this ticket.

## 七档与出站形态 / Seven API values and outbound shapes

| 值 / Value | OpenRouter | Anthropic 直连 / Direct | 其他 OpenAI 兼容 / Other |
|---|---|---|---|
| off | 不传控制字段 / omitted | 不写 thinking / omitted | 不传控制字段 / omitted |
| auto | `reasoning={"enabled":true}` | `thinking`，映射预算 10000 | 不传字段，供应商默认 / omitted |
| low | `reasoning={"enabled":true,"effort":"low"}` | 映射预算 5000 | `reasoning_effort=low` |
| medium | 同形 effort=medium | 映射预算 10000 | `reasoning_effort=medium` |
| high | 同形 effort=high | 映射预算 20000 | `reasoning_effort=high` |
| xhigh | 同形，受端点天花板限制 | 映射预算 32000 | 受端点天花板限制 |
| max | 同形，受端点天花板限制 | 映射预算 64000 | 受端点天花板限制 |

具体档位沿用 `config.TRUSTED_HOST_CEILINGS` 按真实端点降档；未登记端点保守降到 high。`auto` 不保证所有供应商开启：其他 OpenAI 兼容端点不带控制字段。五档面板保持 off / auto / low / medium / high，xhigh / max 仍可通过 API 显式传入。面板与 Chat 的 `/sync/settings` 写同一个配置键；显式发档位的 Chat 请求优先于它。

Specific efforts retain endpoint-based downgrades from `TRUSTED_HOST_CEILINGS`; unknown endpoints are capped at high. Auto enables OpenRouter/Anthropic through their existing translation, but leaves other OpenAI-compatible providers at their default. The panel retains five options; the API accepts all seven. Panel and Chat sync settings share one configuration key, while explicit request values take precedence.

## Anthropic budget 与 temperature

真实 adapter 将 `reasoning.enabled` 转为 `thinking={"type":"enabled","budget_tokens":...}`，最终出站不含 OpenRouter 的 reasoning 对象。预算是 `min(映射预算, max_tokens - 1)`；省略 max_tokens 时默认 8192，所以 auto / high 均夹到 8191。若 max_tokens <= 1024，则不写 thinking，也不覆盖 temperature。额度足够时启用 thinking 并沿用 temperature=1；关闭时 temperature 按请求保留。该换算器本票未改动。

The unchanged Anthropic adapter emits thinking with budget_tokens, not an OpenRouter reasoning object. Budgets are capped at max_tokens minus one. Omitted max_tokens defaults to 8192, capping auto and high at 8191. At max_tokens <= 1024, thinking is disabled and temperature is preserved. When thinking is enabled, temperature remains forced to 1 by the existing adapter. These are current adapter rules, not a promise about every future model.

## 诊断与升级 / Diagnostics and upgrade

- `event=reasoning_effort_resolved source=explicit|panel|default effort=<七档>`：成功规范化并解析后每请求一行。panel 包括库无行时的出厂 off；default 仅空或非法值兜底，不能用它判断用户是否从未设置。
- `event=reasoning_effort_config_invalid increment=1`：非空非法字符串配置，不回显原值。
- `event=reasoning_effort_downgrade`：现有端点降档事件保持原样。Anthropic 既有 budget_clamp / disable 事件也保留。

日志仅用固定来源与枚举值，不含用户、模型、会话或密钥。2.0 起网关缺省不再主动开启思考：依赖原行为的用户在客户端显式传档位，或到面板「对话行为 → 思考强度」选择档位。干净配置的正常日志是 `source=panel effort=off`。详见 [升级指南](UPGRADING.md)。

The resolved event logs only an enum effort and a fixed source. Panel includes factory-default off; default indicates an empty/invalid fallback, not proof that a user never configured the service. Invalid nonempty string configuration logs a fixed event without echoing its value. Existing downgrade and Anthropic clamp/disable events remain unchanged. In 2.0 Kiwi no longer enables thinking by default; explicitly choose an effort or configure the panel to retain the previous gateway behavior.
