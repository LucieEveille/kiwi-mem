# KIWI-PREP-01 P2 · 2026-09-10

依据：Fable《爹爹裁决 v3 · 合成 CC 复核 · 退回 P2》。起点 PR #81 `f168842a3ce29675b37b572a1b63c7a2a500375d`；公开 main 基线 `98e7d5cc5e02ad2310175fd193fb09cdef1198c2`，集成分支 `e5a072682d750729298cca94e0738d4bcb55fe43`。

状态：PA-01 / PA-02 / PA-03 修复与 R-01 文档已交付验证；export 前缀的范围冲突待露露 / Fable 裁决，整批 P2 暂未标完成。PR 保持 Draft，未合并、发布或部署。本文替代 P1 文书中端口解析的范围说明，旧文书保留为历史证据。

## 修复与解析合同

PA-01：update.sh 四处赋值及预检、状态保存、首页与 MCP 探针改用 LISTEN_PORT；不赋值、不 unset、不重新 export PORT。普通更新与 re-exec 均保留操作员 PORT 是否存在及原值，JSON 状态键 port 不变。

PA-02 / PA-03：无助手分支补成对引号、UTF-8 BOM 与 shell 优先；jq 的 awk 补 BOM。两段 awk 均以 LC_ALL=C 运行，保证 BOM 的三字节检查不受多字节 locale 影响。Python helper 原样保留。

P1 的“仅接受十进制”应区分数据外壳与端口内容：BOM、CRLF、成对单/双引号可以被剥除，解析后的值须为 1～65535、1～5 位 ASCII 十进制数字。显式空环境值优先于 dotenv，最终回退 8080。无效值的探针回退不能代替 Compose 对部署配置的验证。

| 行为 | Python（未改） | jq 的 awk | 无助手 awk |
|---|---|---|---|
| BOM | utf-8-sig | 首行三字节去除，LC_ALL=C | 同左 |
| CR / 外部空白 | splitlines / strip | POSIX space trim | POSIX space trim |
| 成对单/双引号 | 去首尾并 strip | 去首尾并 trim | 去首尾并 trim |
| 多条定义 | 最后一条 | 最后一条 | 最后一条 |
| shell 优先 | os.environ.get | `${PORT-$value}` | `${PORT+set}` 判存在 |
| 空 shell 值 | 保留空，port 回退 | 保留空，port 回退 | 保留空，LISTEN_PORT 回退 |
| 非法值 | 8080 | 8080 | 8080 |

R-01 已在 UPGRADING 中英及 CHANGELOG 点名：Starlette 静态文件 Range 206 / 416 / Accept-Ranges 是标准 HTTP 行为变化，未增加访问控制。KNOWN_ISSUES 不改。

## tests-first 与矩阵

tests-only `d754f25` 保留 P1 实现。CI [34417040292](https://github.com/LucieEveille/kiwi-mem/actions/runs/34417040292) 13 方法、36 FAIL、0 ERROR，红因包含 compose_saw_PORT 与探针端口不一致。`7d96d8b` 允许 Windows 跑 Python 宿主子集；`4ab8acb` 让旧基线缺少 jq helper 源码时结束附加源码探针，保留已失败的端口断言。

最终端口断言套旧基线 98e7d5c：Windows Python 宿主子集 17 场景，11 FAIL、0 ERROR；使用 PREP Python 测试环境运行原始更新脚本，不宣称重建整套旧应用依赖。早期缺文件 ERROR 的探针输出已作废，以 prep-p2-baseline-red-final.txt 为准。

T-13 在 Linux 跑 45 格（3 宿主 × 3 环境 × 5 dotenv 形态），另有三宿主 last-wins、无助手 invalid、Python / jq re-exec 两格，共 51 场景。每格检查 compose up 看到的 PORT 是否与操作员逐位相同、所有探针 URL 是否使用预期发布端口、更新状态文件清理。fixture 仅保存测试环境的 PORT，使用假 docker / curl，不启动真实业务容器。

附加探针用真实 docker compose config --format json 验证 15 个配置格，仅读配置；awk 实现探针抽取生产源码，各跑普通、双引号、BOM、CRLF、单引号、多条最后定义六种输入。是否可用与实际结果分别记录，缺运行时不能记 PASS。

## 执行证据

实施提交 fc3cbef 的 [CI 34417645620](https://github.com/LucieEveille/kiwi-mem/actions/runs/34417645620) 两 job 全绿：13 套既有回归、178 条真实 PG16 守卫、13 个 PREP 方法（Linux 无 skip）、框架兼容、Docker 构建、pip check；audit 恰三个获准 ID，四条原始记录中一条重复。29 次变异全 RED，preflight=0 / restored=0。

| awk 实现 | 生产解析器数 × 输入形态 | 结果 |
|---|---|---|
| CI gawk | 2 × 6 | PASS |
| CI mawk | 2 × 6 | PASS |
| CI busybox awk | 2 × 6 | PASS |
| Windows Git 附带 GNU Awk 5.3.2（完整路径另跑） | 2 × 6 | PASS |

真实 Compose config 的 15 个格全部匹配预期端口；未执行 Compose up，此部分无需 Docker daemon。Windows 默认 PATH 没有 gawk 的提示已用完整路径实跑补齐；mawk / busybox 仍以 CI 为证。

3268baf 的 [CI 34417878997](https://github.com/LucieEveille/kiwi-mem/actions/runs/34417878997) 再次两 job 全绿，13 PREP / 178 PG16、框架与镜像、29 RED、三个 audit ID 全部一致。入仓账本取该次原始输出，16 个 source_blobs 与该 head 逐项相等。

## 唯一待裁决：export 前缀

真实 Compose 只读观察为 `OBSERVATION: real compose export prefix published=9000`，确实接受 `export PORT=9000`。当前 Python helper 的正则仅匹配 PORT=，按裁决要求保持未改；另两条解析器也未扩前缀语法。

裁决 P2-2 要求“update_support.py ……不动”；P2-5 又要求若 Compose 采纳 export 前缀“三路径同步支持”，同时限定九文件。这两条不能按当前指定的三个解析器同时落实，已通过聊天提请范围裁决。当前 UPGRADING 明确记为辅助解析器不支持，属于建议边界，尚未被当作露露新批准的例外。

建议：本批维持九文件范围，部署写作独立 PORT=9000，前缀支持另列后续；如裁决本批支持，则先扩定范围，再 tests-first 补三路径。没有把支持此语法宣称为已完成，也没有声称 Compose 不支持。

## 变异范围

旧 K-PREP-23 转挂 T-13。新增 K-PREP-24（覆写 PORT）、25（删无助手引号剥除）、26（分别删 jq / 无助手 BOM）、27（删无助手环境优先）。实际 **27 个编号、29 次执行**：K-2 与 K-26 各两个独立变体。裁决中的 28 次未计全这两个变体，按实际执行记账。

原账本文件重出，head 记录被测提交，source_blobs 仍锁相同 16 文件；文书提交不改变这些源码指纹。原 audit JSON 不改，CI 重扫结果单独核对，三条已批准 MCP 公告以外不加例外。

## 集成预演与边界

本地临时树 release e5a0726 + fc3cbef：唯一冲突 KNOWN_ISSUES.md，SEC 段在前、一个空行、PREP 段在后；其余自动合并，暂存树 2b3cf7ce23b540f14e53902cf3c813c8bf38bbda。SEC-01a 37 OK，PREP 13 方法中 12 OK / Linux 方法 1 skip（T-13 内 Windows 只跑 Python 宿主），test_admin_secrets.mjs PASS。该树未包含后续文书与只读观察增量，不能作为最终预演树 hash。

本机没有 PG16 / Docker / mawk；本地结果不冒充完整 Linux、真库或两套刀的集成证据。Fable 仍须对最终合成树重放验收①②，CC 再复验端口、Range 文案与最终预演树。所有部署、合并、tag 与 Ready 按钮继续等待授权。

P2 增量限制九文件：update.sh、update_support_jq.sh、prep_update_fixture.py、test_kiwi_prep_01.py、kiwi_prep_01_knives.py、原刀账 JSON、UPGRADING、CHANGELOG、本说明。main.py、Python helper、依赖、compose、CI、KNOWN_ISSUES 与旧报告均保留。
