# KIWI-SEC-01b 阶段 B · 施工与验证记录（2026-09-12）

范围：PR #84，base `release/kiwi-sync` / `03484debf3513944c98cf3e212d87878f4b09be0`。应用实现 commit `560ec2b`；包含最终守卫、刀本、CI 和机制文档的验证 commit `c6b6e055d820b3d2d6396a5ce9cb317d4a65b9e6`。PR 保持 Draft，尚未合并或部署。

## 实现与不变量

- `main.py` 在 FastAPI 构造后、全部业务路由之前注册两条 `methods=None` 精确路由，删除两个整前缀 Mount。包装为 `AsgiEndpoint(observe_mcp_access(guard_mcp_access(endpoint, _SECURITY)))`。
- `mcp_access.py` 新增可调用对象 `AsgiEndpoint`，使 Starlette 直接按 ASGI 调用闭包；观察与门卫函数零改写。
- `mcp_server.py` 新增代理对象与两个端点工厂，先预热惰性 session manager，再代理其 handle_request。三个旧工厂保留。
- 三个文件的既有顶层函数、类逐个 AST 对比：零改写。两处 lifespan session_manager.run、calendar 业务函数、名单与门卫规则、SDK 版本、VERSION、升级 gate、更新脚本、抽屉与 admin Mount 均未改变。
- SDK 1.29.1 三文件无 scope path/root_path 读取；handle_request 仍经其请求体限制中间件。路径由外层精确 Route 选择，SDK 保留协议与传输安全处理。

## 红绿与测试夹具

阶段 A `2884359` 红证已独立验收。最终守卫套回 `03484de` 的隔离工作树重放：12 条，35 处断言失败，0 ERROR，仍是原八条红；T-03/04/09/10 绿。T-09 的真实 SDK 客户端握手走 POST，基线可达已按阶段 A 验收裁决记录。

本地目标环境：Python 3.12，mcp 1.29.1、Starlette 1.3.1、FastAPI 0.141.1。SEC-01b 12、BUILD 13、SEC-01a 37 全绿；PREP 13 中一条 Linux 专用测试跳过，其余通过。12 套 Python 回归（含框架兼容）与 3 个 Node 检查通过。

新票使用真实 main 路由、SDK session manager、uvicorn 与 SDK 客户端。观察库和 calendar 查询是夹具，主 lifespan 只启动两个 manager；不启动后台任务、不调用真实上游模型或生产数据库。

为刀本的错误出口补了两类测试夹具处理：已发送的 HTTP 500 按真实客户端响应保留；不符合 JSON/SSE JSON 或 JSON-RPC DELETE 形状时明确断言失败。K-06 初次出现 KeyError/CRASH，未计为有效红；`c6b6e05` 增加字段断言后重出账本。应用实现未为此修改。共享 AST 断言的 PREP/BUILD 依赖写入文件顶部注释。

## 真实 HTTP 矩阵

`evidence/kiwi_sec_01b_http_matrix.json` 记录 77 格，使用真实回环 uvicorn + main + SDK，数据库与 calendar 查询模拟，观察节流时钟每格复位以防零写判据被节流掩盖。全部通过，线程和 socket 已关闭。

| 路径/请求 | 实测 |
|---|---|
| 两条精确 MCP 路径 GET | SSE Accept 200 text/event-stream；JSON Accept 406；calendar 业务零调用 |
| 两条精确 MCP 路径 POST / DELETE | initialize 200；DELETE 405。真实 SDK 客户端另核实例名与完整工具集合 6 / 11 |
| 两条尾斜杠路径，IP 与登记域名，各 GET/POST/DELETE | 307，Location 保留原 Host:port |
| `/memory`、`/memory/`、两条 `/mcp/extra`、`/memory/extra` | 404，外来 Host 同样 404；零观察写入、零门卫拒绝事件 |
| `/calendar`、`/calendar/2026-09-12` | GET 原业务 200；POST/DELETE 405 |
| 外来 Host / 未登记 Origin / 错误 CT | 精确端点分别 421 / 403 / 400 |
| 两条精确端点 4 MiB+1 POST | 413，直接派发保留 SDK 请求体限制 |

## 刀与账本

四本当前账本均在验证 commit 重跑并核 source_blobs；账本提交只增加证据，不改变被测文件。preflight 与 restored 均为 0。BUILD 与 PREP 的锁定集合增加共享的 SEC-01b 守卫文件，防止共享断言变更未进入指纹。

| 账本 | 数量 | 说明 |
|---|---|---|
| `evidence/kiwi_sec_01b_knives.json` | 10 | 新票逐格破坏路由、层序、工厂、方法与文档 |
| `evidence/kiwi_build_01_knives.json` | 23 | K-18 重新定位新包装表达式，BUILD T-10 与 SEC-01b T-08 均抓住；语义保持调换层序 |
| `evidence/kiwi_prep_01_knives.json` | 29 次、27 编号 | 保留 stdout/logging 与 jq/no-helper 两组变体 |
| `evidence/kiwi_sec_01a_knives.json` | 41 | 凭据边界整套重放 |

`kiwi_sec_01a_build_knives.json` 是上一票留下的历史证据；本票以表内四本作为当前验证账本，不把历史 head 当本次证据。K-07 在 Starlette 函数端点分支变成 POST 405，由 T-03 断言捕获；不依赖运行时异常作为红证。

## 文档与检查

机制文档新增中英「挂载与路径」表；UPGRADING 中英更新两条端点行为并保留 token 删除历史；KNOWN_ISSUES 以 `560ec2b` 记集成分支已修；CHANGELOG 加 #84 和行为差异。README/README_EN 两条连接 URL 核对不变，文件零改动。全仓编译与 git diff --check 通过。

## CI 与证据核对

[CI run 34694265448](https://github.com/LucieEveille/kiwi-mem/actions/runs/34694265448) 在验证 commit 上两 job success：SEC-01b 12 / PREP 13 / BUILD 13 / SEC-01a 37 / PG16 184，既有回归、镜像构建通过；四刀 10 / 23 / 29 / 41 全 RED，preflight/restored 均 0。Linux PREP 没有本地 Windows 的跳过项。pip check 通过，pip-audit 39 包、0 漏洞。

四本入仓账本逐字节取自本次 CI artifact，head 均为 c6b6e05；source_blobs 分别 6 / 9 / 17 / 7 项，已逐个核对。PG16 使用一次性库，日志确认清理；模型与 HTTP 边界为 mock，不作为真实供应商验收。

本地还重放 SEC-01b 10 / BUILD 23 / SEC-01a 41，结果均 RED。与 Linux 原文 reason 比较，SEC-01b K-02 有平台事件循环日志差异、K-05 有集合显示顺序差异；BUILD K-02 有 AST 对象地址差异、K-08 有事件循环和流关闭日志顺序差异，触发断言与结论相同；SEC-01a 41 条 reason 相等。不宣称跨平台全部 reason 字节相等，以入仓 Linux CI 原文作为复核记录。


阶段 B 交给独立验收，Ready、合并、部署仍未执行。
