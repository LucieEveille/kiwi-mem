# 思考强度 / Reasoning effort

KIWI-THINK-01（PR #86）用于 2.0 集成分支。用户应能决定是否让网关开启思考，而不是因为客户端省略参数就被网关隐式开启。入口每请求解析一次，普通转发与工具循环共享结果。

## 优先级与边界 / Precedence and scope

**显式 ＞ 面板 ＞ off**：请求 `reasoning_effort` 显式合法值优先；缺席或 null 时再读非 null 的 `reasoning` 对象，没有有效对象控制且无异常字段时读取面板同名配置。配置系统返回出厂默认 off 也算配置来源；空、None 或非法配置防御兜底为 off。请求非法值仍返回原有 400 invalid_value，大小写与首尾空格规范化不变。

`off` 表示网关不主动开启：删除 `reasoning` / `reasoning_effort` 后不添加开启参数。它不保证上游模型自身不推理或不收费；强制关闭与模型能力归后续专项票。`exclude` 隐藏推理内容而不关闭推理。内部 `skip_system_prompt` 请求不主动开启思考，无论面板如何设置。

The precedence is explicit request > panel configuration > off. When the string is missing or null, a non-null reasoning object is parsed next; an object with no effective or invalid controls also falls back to configuration; valid explicit input wins without reading the panel. The configuration getter includes the factory default. Empty or invalid configuration falls back to off. Invalid explicit input retains the existing HTTP 400 contract.

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

- `event=reasoning_effort_resolved source=explicit|explicit_object|object_fallback|panel|default effort=<七档>`：成功规范化并解析后每请求一行。panel 包括库无行时的出厂 off；default 仅空或非法值兜底，不能用它判断用户是否从未设置。
- `event=reasoning_effort_config_invalid increment=1`：非空非法字符串配置，不回显原值。
- `event=reasoning_effort_downgrade`：现有端点降档事件保持原样。Anthropic 既有 budget_clamp / disable 事件也保留。

日志仅用固定来源与枚举值，不含用户、模型、会话或密钥。2.0 起网关缺省不再主动开启思考：依赖原行为的用户在客户端显式传档位，或到面板「对话行为 → 思考强度」选择档位。干净配置的正常日志是 `source=panel effort=off`。详见 [升级指南](UPGRADING.md)。

The resolved event logs only an enum effort and a fixed source. Panel includes factory-default off; default indicates an empty/invalid fallback, not proof that a user never configured the service. Invalid nonempty string configuration logs a fixed event without echoing its value. Existing downgrade and Anthropic clamp/disable events remain unchanged. In 2.0 Kiwi no longer enables thinking by default; explicitly choose an effort or configure the panel to retain the previous gateway behavior.


## 客户端 reasoning 对象与别名 / Client objects and aliases

字符串 `reasoning_effort` 在入口接受 `none → off`、`minimal → low`（有损映射），大小写与首尾空白不敏感；对象 `effort` 共用同一别名表。七档枚举、面板值与 400 消息中的七档列表不扩展。

入口对所有客户端与后端统一解析，不按品牌或地址猜语义。前端输入先归一到网关七档，再走既有后端转换；请求成功不等于上游一定执行了设置。

三步规则：

1. 非 null 的顶层字符串先校验，合法时覆盖整个对象，连对象诊断事件也不产生；非法字符串沿用 400。字符串缺席/null 才解析非 null 对象，非对象沿用 400。
2. 对象字段分类：缺席/null 等于没提供；`enabled` 只认布尔；`max_tokens` 只认非负整数且排除布尔；其它值为异常。按 **enabled:false → effort → max_tokens → enabled:true** 顺序采用合法控制。false 立即短路，不校验低优先级 effort；否则非 null effort 必须合法，仍沿用 400。
3. 无合法控制可生效时：有异常字段，本轮 off、不回退面板；没有异常字段，按面板/default。异常容错是 Kiwi 政策，不是推断字符串 "false" 或负数的意图。

| 输入 / Input | 有效档 / Result | 诊断 / Diagnostic |
|---|---|---|
| `enabled:false`，含非法 effort | off / explicit_object | 若预算异常，field_ignored |
| 合法 effort（含 none/minimal），即使预算为 0 | effort 档优先 / explicit_object | 若 enabled/预算异常，field_ignored |
| 无更高优先级控制，`max_tokens:0` | off / explicit_object，Kiwi 零预算兼容规则 | 若 enabled 异常，field_ignored |
| 无更高优先级控制，正整数预算 | 预算下界取档 / explicit_object | 若 enabled 异常，field_ignored |
| `enabled:true`，无合法 effort/预算 | auto / explicit_object | 若预算异常，field_ignored |
| 只有异常 enabled 或预算 | off / object_fallback | fallback |
| `{}`、全 null、只有未知字段 | 面板/default | ignored |
| 对象缺席/null | 面板/default | 无 |
| 非对象，或未被 false 短路的非法 effort | 400 | 无对象诊断 |

例如 `enabled:"false", effort:high` 仍取 high；`enabled:true, max_tokens:"5000"` 仍取 auto；`effort:high, max_tokens:0` 仍取 high。只有无法识别的控制且无合法控制可采用，才保守落 off。合法开启不得被低优先级异常值否决。

| max_tokens | Tier |
|---|---|
| 0 | off |
| 1–4999 | low（最低映射预算 5000） |
| 5000–9999 | low |
| 10000–19999 | medium |
| 20000–31999 | high |
| 32000–63999 | xhigh |
| ≥64000 | max |

三个诊断事件仅含固定原因与字段名，不含原值或对象原文：

- `event=reasoning_object_ignored reason=no_control_fields`
- `event=reasoning_object_fallback reason=invalid_control_value fields=enabled,max_tokens`（只列实际异常字段，顺序固定）
- `event=reasoning_object_field_ignored fields=enabled,max_tokens`（其它合法控制生效）

对象只选择档位，不透传预算原值。最小预算与 minimal→low 都是有损映射。`off` 只表示网关不发送思考控制字段，上游模型/中转是否仍推理由其自身决定；特定中转的关闭效果归 COMPAT 验收与候选 CAP-01。`exclude` 不解释、随对象被现有 translator 移除；顶层 `include_reasoning` 保留各路径现状（普通 OpenAI 转发保留，工具循环和 Anthropic 转换不带）。

错误保留嵌套 `error` 四键：`message/type/param/code`，其中 `type=invalid_request_error`、`code=invalid_value`。对象路径 `param=reasoning`：非对象消息以 `reasoning 必须是对象` 开头，非法 effort 以 `reasoning.effort 必须是` 开头；字符串路径仍为 `param=reasoning_effort`。消息不回显输入，本次不新增拒绝形状。

English: input normalization is independent of client brand and backend address. A valid non-null explicit string wins over the entire object without object diagnostics. Otherwise classify enabled and max_tokens as absent/null, valid, or invalid. Apply false first (without validating effort), then effort/aliases, nonnegative integer budget, and true. Invalid non-null effort still returns 400 unless false short-circuits it. Zero budget is a Kiwi off alias; positive budgets select tiers, not exact caps. If no valid control applies, invalid controls resolve to off without panel fallback; empty/all-null/unknown-only objects use the panel. This is a conservative Kiwi policy, not a guess about negative numbers or string booleans. Valid higher-priority controls still win over invalid or lower-priority controls.

The three events above contain only field names and fixed reasons. Sources are explicit_object for valid controls, object_fallback for conservative off, or panel/default for ignored objects. No new rejection shapes are introduced. The existing outbound layer is unchanged; off cannot guarantee that an upstream model stops reasoning. COMPAT/CAP-01 own that capability boundary.

## 已实证的第三方客户端出站形态 / Pinned client audit

以下为 2026-09-22 源码盘点的固定快照，描述指定 provider/model 路径；不代表后续所有版本、设置组合或端到端真机验收。

| Client / snapshot | 关闭 / Off | reasoning object path |
|---|---|---|
| [RikkaHub 94504b5](https://github.com/rikkahub/rikkahub/tree/94504b5cabeba59304e6343ca61fa43c181a7126) | `reasoning_effort:none` | 普通自定义 OpenAI 路径不发对象 |
| [Cherry Studio 322e794](https://github.com/CherryHQ/cherry-studio/tree/322e794a99d93a51f905cecb327df4c32d291eb5) | Custom 路径 `none` | OpenRouter provider 路径 `{effort}` / `{max_tokens}` |
| [Chatbox 0cf406c](https://github.com/chatboxai/chatbox/tree/0cf406cbd93197a89487c740cb101bef36641d35) | gpt-5 系模型路径 `minimal` / `none` | 自定义 OpenAI 路径不发对象 |
| [Kelivo 3762450](https://github.com/Chevey339/kelivo/tree/3762450a2561786a4ee0e9d5a44d40947cca345c) | 普通路径省略字段 | provider 名含 openrouter 的路径可发 `{effort}` |
| [Operit dbf7191](https://github.com/AAswordman/Operit/tree/dbf71916fae9750cfdc9f9a774f5a0fee56633fb) | 普通路径省略字段 | OpenRouter 类型 `{effort}` / `{max_tokens}`，预算最低 1024 |
| [SillyTavern 06bde93](https://github.com/SillyTavern/SillyTavern/tree/06bde939fb1e9c4c8d8641d810f0a916b5bce127) | 取决于 source/model 条件 | 思考 UI 含 minimal；是否发 effort 受模型与 provider 分支限制 |

六家均未实证发送零/负预算、非布尔 enabled 或空对象；异常处置为防御性合同。

None of these six pinned audits demonstrated those malformed/empty shapes; the fallback policy is defensive.

These are source-level observations at pinned commits, not a current-version or all-settings compatibility guarantee. A client omitting both fields falls back to Kiwi's panel setting. Final release acceptance still requires client testing on the integrated release candidate.
