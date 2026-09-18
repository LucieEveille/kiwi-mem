# Embedding identity and alignment / 向量身份与对齐

KIWI-EMB-01 · 2.0 integration mechanism v2 (2026-09-18; EMB-01-P diagnostics and lease hardening)

## 理念与身份

语义距离只有在同一模型、同一端点及同一文本口径下才有意义。用户切换嵌入模型后，旧向量继续保留，但不参与新模型的比较；用户确认费用后才重建旧数据。模型失败不能把旧向量贴到新正文上。

`memories`、`mem_scenes`、`project_file_chunks` 在原 `embedding` 列旁增加四列：`embedding_profile`（路由身份）、`embedding_model`、`embedding_dim`、`embedding_source_hash`（生成时文本的 SHA-256）。五列一起写；失败时五列一起清空。原有非空向量迁移为 `unknown`，不猜测其模型。schema 变更为幂等加法。

profile = SHA-256(UTF-8 JSON `["emb-v1", source_tag, endpoint_identity, model_id, api_format, "text-v1"]`)，JSON 使用 `ensure_ascii=False,separators=(",",":")`。source_tag 是 `provider:<id>` 或 `env`。端点身份的 scheme/host 小写、端口显式、path 去尾斜杠，不允许 query、fragment、userinfo。凭据与供应商名称不进身份；轮换钥匙不要求重建。

| 路由条件 | 行为 |
|---|---|
| 面板模型绑定启用的 OpenAI 格式供应商，URL 与 Key 可用 | 使用该供应商的 URL、Key、模型 |
| 面板供应商无 Key / Anthropic 格式 / URL 无效 / 未绑定 | 尝试完整 env URL + env Key；模型取面板值，缺省才取 env |
| 配置/供应商数据库读取异常 | fail closed，无路由，不用 env 掩盖故障 |
| env 不完整或无模型 | 无路由；状态口给原因 |

原生 Anthropic 格式不支持此嵌入请求。OpenAI 格式的中转站可以连接不支持嵌入的模型，格式检查无法证明模型能力，必须实际测试。

## 生成与比较

记忆文本为 `title + " " + content`（无标题仅正文）；场景沿用 `build_scene_embedding_text(title, atomic_facts)`；文件块用原内容。所有九组持久化分支使用同一五列 payload，包括锁内原子写、普通更新、软化、自动回填、场景、文件块、整理和 Dream 合并。锁内不发模型请求。

`EmbeddingResult` 保存 vector、model_id、profile、dim、provider_id，身份来自发请求时的路由快照。可用向量是非空数值 list，不允许 bool、NaN、Infinity、零范数或非有限范数；余弦使用缩放归一，有限大值如 `[1e308]` 可用，长度不同返回 None。

批量响应必须含等量条目，每条 `index` 必须为非 bool 的整数、在范围内且不重复。结构有歧义则整批等长 None；合法乱序按编号还原；单槽向量无效仅该槽 None。

三处数据库检索先 SQL profile 筛选，再检验向量、维度及文本 hash。无效向量为 missing，身份或文本不符为 stale。记忆没有查询向量时保留关键词降级；场景/文件块返回空结果。抽屉缓存整体发布单一 profile，新世代可废弃迟到结果（包括全失败）；查询身份不匹配时当前请求走关键词并调度刷新。

## 接口与任务

* `GET /admin/embedding-status`：零模型请求；三表检索有效行的 current/stale/missing、待处理字符数、抽屉身份、任务回执。记忆系统关闭时沿用既有关闭提示。扫描成本 O(N)。
* `POST /admin/embedding-rebuild`，`{"scope":"stale"}`（缺省）或 `all`：无路由 409，非法 scope 400，接受/复用任务 202。每次重新检查依据当前数据库，新增内容会进入新任务。
* `POST /admin/embedding-probe`：发送固定短文本，可能产生少量费用。无路由 409、内部故障 500；有路由的上游体检回执 HTTP 200，即使上游失败。没有 `error` 键，成功由 `ok` 判断。
* `GET /admin/migrate-embeddings`：410 `deprecated`，不再产生付费写操作。
* 旧 `embedding-stats` 保留七键及全记忆表口径，另附新 `embedding_status`。

任务及条目落库，只有一个 running 任务。worker 使用随机 owner token、两分钟租约与行锁；认领用条件 UPDATE，后续每次写都先在同一事务确认 owner/token/未过期/running。向量 CAS、条目和计数同一事务提交。CAS 核源文本及类型/状态，变化则 skipped，避免覆盖并发编辑。恢复只处理 pending 条目，不重复累计。

租约判断与续租期限使用 `clock_timestamp()`。`_assert_owner` 先取得 job 行锁，再单独读取真实当前时间核租约；把时间条件只放在 `FOR UPDATE` 的 WHERE 中仍可能在等锁前求值。事务内 `NOW()` 固定于事务开始，不能证明等锁结束后的租约有效。拿锁后已过期则抛 `LeaseLost` 并回滚，续租、终态与进度均不写入；有效 owner 持锁到事务提交，其他 owner 的认领等待同一行锁。普通记录时间戳仍可用 `NOW()`。

启动时恢复 running 任务；其他进程持有租约时每十秒检查。非上游异常记录稳定错误码，保留 running，租约过期后可继续。上游单槽失败计入 failed，任务仍可结束；失败保留待处理身份，下一次重新检查可选中。

换模型检查点为每批前、外呼后、每个结果写入前核结果 profile。当前路由消失也按 target_changed 中止，本批外呼后发现变化则整批丢弃。它不提供跨任意配置写入瞬间的全局原子保证；结果不会冒用其他身份，任务反馈可能延后到下一批或重新检查。

## 面板与诊断

默认嵌入模型旁提供向量对齐、测试嵌入。状态区区分无路由、正在执行（2 秒轮询）、租约过期可继续、本轮结束且展示失败与跳过数、换模型中止、已对齐/待处理。开始前重新读数量并确认费用；没有“精确重试失败 N 条”的承诺。

默认模型保存成功自动测试一次，手动按钮可重复测试。供应商及模型绑定增删改只使旧诊断失效。输入世代与页面 token 随保存请求传递，丢弃旧保存/旧探针回执；相同世代的重复保存不取消唯一的探针。默认模型写操作排队，避免 A→B→A 请求乱序。离页 abort、移除监听并停止轮询。

诊断固定键：`ok,error_code,source,provider_id,http_status,profile,dim,elapsed_ms,tested_at,upstream_message_truncated,upstream_message_hidden,provider_name,model_id,endpoint_host,upstream_message,upstream_request_id`。后五项可控字符串统一脱敏；程序生成身份/分类/时间等不脱敏。请求编号仅接受 1–128 位字母数字下划线横线。

摘要只取 `error.message` 或顶层 `message` 字符串。先检查完整内容中的已知 Key（无最小长度）与 URL 编码 Key、Bearer、sk-模式、URL userinfo、危险控制字符；命中则该字段 null，hidden=true。已知 Key 比对使用原文、仅把 `%xx` 十六进制转为大写的副本、一次 `unquote` 的副本，覆盖标准、小写、混合大小写百分号及被编码的普通字符。钥匙本身仍区分大小写；安全字段的原文不受这些比对副本影响。随后折叠空白并截到 2000 字；面板先显示 200 字，可展开并复制完整受控诊断。不承诺 base64、任意编码或任意层数的递归 URL 解码。诊断仅存页面内存，不写库或触发抽屉刷新。

`security.py` 在进程启动时向 `httpx` 与 `httpcore` logger 注册幂等窄过滤器，仅匹配客户端 `HTTP Request: %s %s "%s %d %s"` 五参数摘要，把供应商控制的原因短语替换为 `<reason-redacted>`，保留方法、URL、协议与状态码。其它日志及日志级别保持原状。这是覆盖该日志格式的进程级防御纵深，不代表任意 HTTP 调试日志都已脱敏，也不替代业务诊断脱敏。当前真实 TCP 路径产生 httpx INFO 摘要；httpcore 同格式注册另有合成日志守卫。

## English

Vectors carry route profile, model, dimension and source-text hash alongside the existing vector. A model switch excludes previous identities from semantic comparisons; old vectors become `unknown` on upgrade and require an explicit, potentially billable rebuild. Credential rotation alone does not change identity. Memory, scene and file text builders are shared across writes and rebuilds.

The profile is SHA-256 of compact UTF-8 JSON `["emb-v1", source_tag, endpoint_identity, model_id, api_format, "text-v1"]`. Source is a provider ID or env; canonical endpoints use lower-case scheme/host, explicit port and a trailing-slash-free path. Keys never enter the recipe. A complete env route can be used when a provider is unsuitable; configuration database errors fail closed.

Finite nonzero numeric lists exclude booleans; scaled cosine rejects invalid/different-length inputs. SQL identity filtering and Python text/dimension validation both apply. Batch indices must be an exact permutation of input positions; ambiguity rejects the whole batch, while a bad vector rejects only its slot. Drawer caches publish one generation/profile atomically and fall back to keyword routing on mismatch.

Status performs no model requests and scans eligible rows in O(N). Rebuilds use one durable running job, two-minute leases, owner checks and compare-and-swap writes. Vector, item state and counters commit together. Crashes resume pending work after lease expiry. Model changes or loss of a route stop work; checks before and after each batch plus per-result identity checks prevent mislabeling, without promising atomic configuration changes across all concurrent requests. Finished receipts remain visible for 24 hours. Failure/skipped counts remain explicit; retry re-enumerates current pending data.

Lease checks use live `clock_timestamp()`. The owner check acquires the job row lock first, then checks expiration in a separate statement: transaction-start `NOW()` and pre-lock predicates cannot establish validity after a lock wait. An expired owner rolls back without renewing or writing progress/final state; a valid owner holds the lock through the vector/item/counter transaction, serializing new claims.

The probe sends a fixed short text with a 15-second timeout and redirects disabled. Its HTTP 200 receipt can describe upstream failure; 409 means no route and 500 an internal failure. It never persists or refreshes drawers. Only bounded, redacted diagnostic fields cross this special endpoint. Full-text redaction precedes the 2000-character limit; the UI initially shows 200 characters. Exact and URL-encoded credentials are detected without a length exemption; arbitrary encodings are outside the guarantee. Save and edit generations prevent stale receipts; leaving the page cancels polling and ignores late responses.

Credential comparisons preserve key case and check the original, percent-hex-normalized and once-URL-decoded strings. Lower/mixed hex and escaped unreserved characters are covered; base64 and arbitrary recursive encoding are not guaranteed. A process-wide narrow filter on the httpx and httpcore loggers replaces only the reason argument in their five-argument HTTP Request summary signature. Method, URL, protocol, status, unrelated records and logger levels remain intact. This is defense in depth for that signature, not a guarantee for arbitrary debug logs.

Native Anthropic format is excluded, but an OpenAI-format relay may still route to an unsuitable model. Use the actual embedding probe to establish capability. Rebuild and routine missing-vector generation incur provider embedding charges. The retired GET migration endpoint returns 410. The panel never estimates dollar cost or promises an exact failed-item-only retry.
