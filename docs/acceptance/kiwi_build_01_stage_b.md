# KIWI-BUILD-01 阶段 B 实现与验证

日期：2026-09-10。PR #82，Draft，base release/kiwi-sync。阶段交付，等待 Fable 验收及 CC 独立对抗；不代表可合并或已发布。

## 材料与基线

读取施工指令书 v1.1、阶段 A 验收 v1、B-04 裁决 v1、仓内 AGENTS / Release Acceptance、后端构建纪律相关章节；落实 F-1 与 B-04 的授权修正。

基线 6b2b43d0b746fb9c69f52f54d0347bd63e3ae9f4，main b01a0c5（v1.7.0）。阶段 A 后 tests-only 修正 8f1f848（Content-Type 415），c059bd2（构造输入 identity + 内部等值副本 + 三对象不变），实现 29c3b02。证据提交的被测 head/source_blobs 以仓内 JSON 为准，文书提交不反写自己的 SHA。

## 逐文件交付

| 文件 | 最终行为 |
| --- | --- |
| requirements.txt / Dockerfile | 仅三 pin：mcp 1.29.1、httpx 0.27.2、uvicorn 0.31.1；ECR Python 3.12 基础镜像 |
| mcp_access.py | 惰性名单构造（保留更新器无依赖解析能力）、Host/Origin/Content-Type 门卫、IP scope 副本、SDK logger 窄 filter、enabled 九键、固定启动摘要 |
| mcp_server.py | 两构造器输入同一 _SECURITY；SDK 内部等值副本合法，无回绑 |
| main.py | observe(guard(SDK)) 两处、启动摘要入口、status version=VERSION；原整前缀挂载仍归 SEC-01b |
| test_kiwi_build_01.py | 13 组真实 SDK/假 DB 守卫；B-04 构造记录器不替换 SDK 实现；本地服务 teardown 有界 |
| test_kiwi_prep_01.py | 阶段 A 六条授权反转 + README 英文 token 跟随；其余更新守卫未改 |
| kiwi_build_01_knives.py | 23 个精确锚点、RED/SURVIVED/CRASH、字节还原；K-2 同时跑 T-02 和 T-10 |
| kiwi_prep_01_knives.py | K-3/4/21/22 重锚，账本 reanchored_by=KIWI-BUILD-01；27 编号 29 次执行 |
| check_build_audit.py / ci.yml | 独立零漏洞闸，保留 PREP 历史三 ID checker；移除临时 MCP1.12.4 pin；新增 BUILD / SEC 刀及证据 artifact |
| README 中英 / UPGRADING / mcp-transport-security / KNOWN_ISSUES / CHANGELOG | 公版部署路径、稳定错误、IP 与 Origin 边界、九键观察表、SDK 副本与 Host 改写、4MiB、未发布和 gate 边界 |

.env.example 和 compose 已由 PREP 配好，两项键名与值保持原样。版本两处仍 1.7.0，upgrade_gates.json=false。database/security/config/tool_drawer/mcp_client/anthropic_adapter、更新脚本与 SEC 守卫未改。

## 红证与夹具修正

F-1 corrected tests-only：旧实现 BUILD 13 failures、0 ERROR。B-04 新 T-02 套旧实现仍 assertion failure（build_transport_security missing），0 ERROR。说明：旧树在缺实现入口处即红，深层矩阵以实现后绿证为准。

真实 MCP ClientSession initialize/list_tools 的 streamable HTTP 与 SSE 两路径均经过原 mcp_client.py。SSE 常驻连接 teardown 使用 uvicorn timeout_graceful_shutdown=1，保留五秒线程结束断言；属于测试进程清理，不改变产品断言或客户端代码。SDK/Starlette 的弃用与清理 ResourceWarning 如实保留，不据此宣称协议失败。

## 结果

[CI run 34460740427](https://github.com/LucieEveille/kiwi-mem/actions/runs/34460740427)，被测实现 head `29c3b02aab8407bba27d99779a98aad402ebeb20`：两个 job 全成功；BUILD 13 / PREP 13 / SEC 37 / PG16 184、既有回归与 Node、框架兼容、ECR 镜像构建均通过。

三套 CI 原始账本：BUILD 23/23 RED（8 个 source_blobs）、PREP 27 编号 29 次全 RED（16 个 blobs）、SEC 41/41 RED（7 个 blobs）；每套 preflight/restored 均 0，指纹与被测实现逐一相等。账本原样入仓；PREP 页首 reanchored_by 已设。Windows BUILD 也 23/23，去掉 AST 对象地址后 22 把原始红因一致；K-8 的断言把整段捕获日志拼进红因，Linux selector 与异步清理日志和 Windows 不同，但同为 BUILD-direct.example 进入日志被抓，原始输出保留，不宣称跨环境红因逐字全等。

本地：BUILD 13 通过，BUILD 23/23 RED，SEC 37 与 41/41 RED；PREP 13 组报告 OK（1 skipped），Linux fallback、jq/部分 awk 与真实 Compose 本机不可用，不能计为本地全覆盖。其余本地回归仅 gateway_tool_streaming 因缺 PG 阻塞，CI 的真实一次性 PG 路径单列。

额外真实 SDK 探针：memory/calendar 对 4MiB+1 字节体均 413，固定文本 Request body too large；没有真实供应商、Zeabur 或生产请求。IP 的 raw ASGI IPv6 覆盖不等于真实 IPv6 socket；独立浏览器对抗仍归 CC。

最终仓内 audit 原文来自该 CI 的干净 Linux Python 3.12 运行环境：39 项依赖、零漏洞、pip check 无冲突。Windows 40 项结果保留为此前预检来源，未冒充 Linux 最终扫描。零漏洞闸的独立探针确认：空报告、跳过项、漏洞项均拒，干净项通过。

本次最后的文书提交仅入证据与本报告；所有刀账锁定的源码 blob 不变。T-01 消费的 audit 从 Windows 零漏洞替换为 Linux 零漏洞，替换后本地 BUILD 13 重跑通过。

## 尚待外部验收

保持 Draft，下一步 Fable 按树验收，再 CC 七点对抗。IP 自动放行若出现已授权范围内反例，按裁决回退精确 IP 登记。无合并、部署、VPS/Notion 写入。测试实例指纹与 Zeabur 域名变量展开需部署后另验，不在本阶段冒充已完成。

## B-04 收口

此前 stage_b_blocked.md 为历史停点记录。用户 B-04 裁决已落实于 c059bd2 与 29c3b02，当前无该阻塞；没有改写 SDK 内部对象。后续验收仍以本报告、实际树和原始刀账为准。


## 阶段 B 验收 F-2 / N-1 小补丁（2026-09-10）

被测修正 commit：74df0e2738fb554ff4aee0b161ab42fb86cdf4f7。仅改 T-09 两处乱码为“预告”，并在机制文档差异集加入 (c) 空值 Origin 头：门卫 403、SDK 视同缺失放行；应用代码未改。依阶段 B 验收 v1 §五，CC 差异口径以三类为准，第四类差异才是新增反例。

UTF-8 严格回读测试全文；AST 非 ASCII 字符串恰为两个“预告”，没有乱码。BUILD 13 绿；BUILD 23/23 RED，preflight/restored 都为 0，原始新账本入仓。另在仓外探针临时令启动摘要输出“预告”：T-09 assertion failure 正确触发，0 ERROR；字节还原后再跑 BUILD 13 全绿，证明修正的臂确实工作。此额外探针不计入正式 23 刀。

PREP / SEC 原账本的 16 / 7 个 source_blobs 与修正 head 逐一相同，按裁决不重出。上一轮全绿 CI 34460740427 为实现基线证据；本次只执行点名的小补丁重验，不把旧 CI 写成新 head 的运行结果。最后一笔只更新 BUILD 账本与本节文书，被测 commit 与账本自身 commit 分开，源码指纹保持一致。

保持 Draft，下一步 Fable 快核本补丁 diff，之后再由用户转交 CC；未合并、部署或改动生产。
