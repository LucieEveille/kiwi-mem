# KIWI-PREP-01 阶段 B 施工证据 · 2026-09-09

状态：阶段 B 已交付，Draft PR #81 → main，停下交 diff。独立验收、临时集成树验收、CC、发布按钮均未完成。

## 依据与范围

- 冻结总纲 v1.5.2，原件 SHA-256 `45446c4971a7a394d874ffe9a01c5fe42ae8e1d8c459d50ad6a53be602c6ae74`。
- 施工指令书 v1.0.1，SHA-256 `04cb2aa29f991307e0889d80077747eaab807154844c2256bb2853f315fd23c4`。
- 9/9 阶段 A 验收及阶段 B 补充：A-1 捕获 root / mcp logger，K-PREP-2 增 logging 变体；A-2 畸形与空 Host 只计 foreign、不记值。
- 基线 `98e7d5cc5e02ad2310175fd193fb09cdef1198c2`。PREP 分支独立于 `release/kiwi-sync`，未夹带 SEC-01a。
- 版本 1.7.0；本票不启用 MCP Host / Origin 保护，不改变旧挂载顺序，不改 `mcp_server.py`。

## 红证与验证层次

阶段 A tests-only `e1f2994`：CI [34344700120](https://github.com/LucieEveille/kiwi-mem/actions/runs/34344700120)，旧 13 套回归与 177 条 PG16 守卫通过；新增缺表和缺模块断言红。

阶段 B tests-only `546309a`：CI [34346289020](https://github.com/LucieEveille/kiwi-mem/actions/runs/34346289020)，11 个 unittest 方法、17 个 FAIL、0 ERROR。T-04 位于 PG 套件；T-12 的“没有接入保护”在旧代码上本就成立，不制造假红。此提交先于运行实现 `9f7d94e`。

被测实现 `801f613e940c542d84582cc81379d01c93d79ff5`：CI [34349320515](https://github.com/LucieEveille/kiwi-mem/actions/runs/34349320515) 两个 job success。13 套既有回归、178 条 PG16 守卫、12 个应用 / 脚本 unittest（Linux 无 skip）、框架兼容、Docker 构建、pip check 均通过。

账本从该 CI 原样提取：22 个编号、23 次 RED、preflight=0、restored=0，16 个 source_blobs 全部与实现 head 相等。后续封存提交只添加证据 / 文档，不改这些源码；验收以 source_blobs 核对 PR 顶，不要求账本自引用其所属提交。

本地：13 套既有回归通过；应用 / 脚本 12 个方法，11 OK、Linux PATH 矩阵 1 skip；框架兼容与 pip check 通过。Linux CI 补齐该矩阵、真库与 Docker。

证据边界：

- 应用守卫使用真实 FastMCP 与真实 session manager；观察存储使用 SQL 边界 fake。T-02 正常 Host 矩阵走 `main.app` 的实际 memory 挂载，仅替换 lifespan，避免启动数据库初始化与后台任务。
- T-03 在独立 app 中比较 memory / calendar 包装前后的状态码、头、体；它不证明旧 `/calendar/mcp` 业务路由冲突已修复，该事项属于 SEC-01b。
- T-01 / 02 / 03 的 `no_values` 均合并 stdout、stderr、root 与 mcp logger、fake 数据库全部行与 SQL 参数。A-2 覆盖空 Host、畸形方括号、含空格 Host。
- PG16：CI 使用一次性数据库，验证 178 条（原 177 + 单行表幂等与 CHECK 一臂）；脚本清理数据库。本地无 PostgreSQL / Docker，真库与镜像证据来自 CI。
- 更新脚本使用临时 bare remote / source / deploy 仓及假 docker、curl、wget；备份内容也是夹具，不触达真实 Docker 或用户数据库。
- Linux 额外矩阵：实际限制 PATH，分别只有 jq+curl、jq+wget、Python+wget；验证阻断、改 `.env` 后续跑、备份一次、错误探针回滚与状态清理。Windows 此矩阵明确 skip，由 Linux CI 补齐。
- 框架兼容：真实 TestClient lifespan 在独立子进程中启动两次；`MEMORY_ENABLED=false`，检查 admin HTML、文件上传、CORS。SSE 使用既有 stream capture 守卫；不涉及真实模型调用。
- 22 个具名变异编号、23 次执行（K-PREP-2 stdout / logging）。脚本变异作用于 Python 主路径；jq/wget 额外矩阵为行为回归，不宣称这些分支另有同等变异覆盖。

## 逐文件 diff 导航

| 文件 | 改动 |
|---|---|
| `requirements.txt` | fastapi 0.141.1，新增 starlette 1.3.1；其余行保留 |
| `mcp_access.py` | 无地址值的观察、计数、九键状态、启动预告 |
| `database.py` | 独立单行表，幂等 DDL 与 id=1 CHECK |
| `main.py` | 导入、两处 mount 包装、状态路由、启动预告、两处 1.7.0 |
| `scripts/update.sh` | 更新前预检、明确继续、续跑状态、MCP 有界探针 |
| `scripts/update_support.py` | Python 版数据解析、状态、预检与 HTTP 探针 |
| `scripts/update_support_jq.sh` | 无 Python 宿主的 jq 后备实现 |
| `scripts/prep_authority.jq` | jq Host 登记格式校验，与 Python 跑对照矩阵 |
| `scripts/upgrade_gates.json` | 本票 gate=false |
| `.gitignore` | 忽略临时续跑状态 |
| `docker-compose.yml` | 透传两项 MCP 登记变量 |
| `.env.example` | 两项登记变量及预告说明 |
| `README.md` | 升级预告、变量说明、Quick Tunnel 限制 |
| `README_EN.md` | 英文 2.0 notice 与部署变量 |
| `docs/UPGRADING.md` | 原理、配置步骤、绕过与 fail-open 边界、风险例外 |
| `CHANGELOG.md` | 1.7.0 准备版行为及风险例外 |
| `KNOWN_ISSUES.md` | 风险例外、预检未验证情形、Quick Tunnel |
| `scripts/test_kiwi_prep_01.py` | T-01～12（T-04 在 PG）与 A-1/A-2、宿主兼容矩阵 |
| `scripts/prep_update_fixture.py` | 完全隔离的更新脚本夹具 |
| `scripts/test_kiwi_safety_sync.py` | 原 177 条之后追加 PG-01 |
| `scripts/test_prep_framework_compat.py` | 框架升级兼容回归 |
| `scripts/kiwi_prep_01_knives.py` | 实际施刀、精确锚点、恢复、RED / CRASH 区分 |
| `scripts/check_prep_audit.py` | 仅接受冻结的三个 MCP 漏洞编号，拒绝其他结果 |
| `.github/workflows/ci.yml` | 原两个 job 内增加守卫、镜像与刀账 / audit；无新凭据 |
| `docs/acceptance/v1.7.0.md` | 发布验收草稿，未执行项保留 BLOCKED |
| `docs/acceptance/kiwi_prep_01_stage_b.md` | 本交付说明 |
| `docs/acceptance/evidence/kiwi_prep_01_knives.json` | 最终实现源码 blob 与逐刀红因，已从 CI 原样提取 |
| `docs/acceptance/evidence/kiwi_prep_01_audit.json` | pip-audit 原始 JSON，已从 CI 原样提取 |

## 已发现并处理的施工问题

- CI 步骤位于 PG 之后，通过条件表达式仍收集新应用守卫红证；9/9 已裁决“位置记档、不改书”。
- 浅检出无法读取基线提交对象：T-11 改核已确认的 `mcp_server.py` 基线 blob `bc7c1892a21b719b5733bfae9ec3cf69cb0b719f`，避免依赖本地完整历史。
- CORS 冒烟补显式测试 Origin，避免默认未配置 Origin 导致夹具自身 400。
- 启动日志哨兵用专有无效 Origin，避免把 JSON `null` 误认作地址泄露。
- jq 续跑状态控制字符校验修正多余转义；隔离 PATH 测试先发现正常备份路径被拒，修复后重跑。
- Python / jq IPv6 尾部 IPv4 校验对齐，拒绝前导零；登记采用 ASCII / Punycode 域名，文档已说明。
- wget 的 idle timeout 不能限制持续分段响应：Python 有总 subprocess timeout；jq 用 `timeout 7` 加 wget `-T 5`。缺少可用工具时如实提示未验证，不把 HTTP 405 视为健康。

## 风险与后续验收

依赖扫描只剩冻结的三个 MCP 公告，`pip check` 无冲突。扫描实际返回 4 行、3 个唯一编号（PYSEC-2026-1617 重复一次），原始 JSON 不去重；按唯一公告集合验收，不把重复行算成新漏洞，也不吞掉其他编号。

warning 如实保留：pydantic-settings / MCP lifespan 定义警告、Starlette TestClient 的 httpx 弃用提示；应用测试还出现 AnyIO `MemoryObjectReceiveStream` ResourceWarning。它们未造成守卫 ERROR，尚不能据此推断生产泄漏，也不为消警告修改 SDK。

CI 另有既有 action 运行时升级提示（checkout@v4 / setup-python@v5 的 Node 20 被平台切至 Node 24），两个 job 均成功，本票未升级 action 版本。

PREP 的 fail-open 不保证每个用户都经过提醒：旧脚本升级至 1.7.0 不会追溯获得新续跑逻辑；Zeabur 自动部署绕过此脚本；没有 Python / jq 的宿主会提示未能验证，脚本自身需续跑时恢复原代码并停止。jq+wget 使用 coreutils `timeout`；缺少该工具时探针不能通过。

下一步由独立验收核 PREP head，再在临时树合成 `release/kiwi-sync` 与 PREP，解决并记录冲突，跑 SEC-01a 全套与 PREP 全套；之后 CC。所有合并、Ready、tag、部署尚未执行。
