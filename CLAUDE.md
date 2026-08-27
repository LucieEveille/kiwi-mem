# CLAUDE.md — kiwi-mem 施工与验收守则（给 Claude Code 看）

你在这个仓库里施工时，除了完成任务本身，还要按本文件执行**阶段验收**并留下**可追溯的报告**。本文件是规矩，不是建议；不清楚时按最保守的一档做，并在报告里写明。

施工前先阅读 `AGENTS.md`。三份文件各管一层：

- `AGENTS.md` 管全仓库共同边界、施工流程与授权纪律；
- `docs/Release Acceptance.md` 管正式验收项目、通过标准与证据要求；
- 本文件只补充 Claude Code 的具体执行方式。

本文件与 `AGENTS.md` 冲突时，以 `AGENTS.md` 为准；具体测试内容或通过标准冲突时，以 `docs/Release Acceptance.md` 为准，并在交付报告中指出冲突。

---

## 0. 三条铁律（先读）

1. **报告只写做过的事。** 没跑的写"未跑"，跑不了的写 `⏸ BLOCKED` 并写清缺什么，需要人做的写"待人工"。**绝不把"应该没问题"写成 PASS。** 一份诚实的半绿报告，比一份漂亮的假全绿有价值一百倍——因为下一位（人或模型）会照着它决定发不发版。
2. **验收清单是权威，本文件只是入口。** 测什么、怎样算过、证据记什么，全部以 `docs/Release Acceptance.md` 为准。清单和本文件冲突时以清单为准，并在报告里指出冲突。
3. **验收环境必须一次性、必须隔离。** 用独立 compose 项目名、独立数据卷、带前缀的测试数据、唯一哨兵串当密钥；**绝不**对任何真实使用中的库做清空/导入/旧版本写入。做完清理并用 SQL 证明无残留。（细则见清单 §〇。）

---

## 1. 什么时候要跑验收

| 触发 | 做什么 |
|---|---|
| **一张票（PR）施工完成、准备交付** | 跑 §2「PR 级自检」——只是常规交付前自检，不产出验收报告 |
| **明确的发布候选版本**（露露/任务说明明确给出目标版本，并说"准备发版"、"跑 Release Acceptance"，或版本号被改动） | 跑 §3「版本验收」——按清单逐项执行，**产出报告** `docs/acceptance/vX.Y.Z.md` |
| **阶段收口但尚无目标版本** | 跑 §2「PR 级自检」，结果留在 PR/阶段交付说明；询问目标版本，**不创建** `docs/acceptance/` 报告 |
| 不确定属于哪种 | 按 PR 级自检做，并在交付说明里确认"是否已有目标版本并需要跑版本验收" |

---

## 2. PR 级自检（每票必做，最小集）

```bash
set -euo pipefail

python -m compileall -q .
git diff --check

# 13 套既有回归：与 .github/workflows/ci.yml 保持一致，任一失败立即停止。
python scripts/test_drawer_stability.py
python scripts/test_gateway_tool_streaming.py
python scripts/test_stream_capture.py
python scripts/test_calendar_summary_generation.py
python scripts/test_calendar_json_parser.py
python scripts/test_mcp_recall.py
python scripts/test_compression_reasoning.py
python scripts/test_calendar_delete_atomicity.py
python scripts/test_mcp_calendar_sections.py
python scripts/test_calendar_period_guards.py
python scripts/test_admin_panel_cache.py
node scripts/test_admin_panel_nav.mjs
node scripts/test_calendar_period_defaults.mjs

# 真库守卫（需要本机 PostgreSQL 16；没有则依赖 CI 结果并在交付里注明）
KIWI_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  python scripts/test_kiwi_safety_sync.py
```

守卫脚本会自己建/删一次性数据库，不会碰 DSN 指向之外的库；它**拒绝**没有 `KIWI_TEST_DATABASE_URL` 时回退，别绕。

CI 上对应：`syntax-check` job；`behavior-tests` job 的"运行既有开源回归脚本"与"运行 S1-S6 永久真库行为守卫"两个步骤。交付时给 Run 号。

---

## 3. 版本验收（产出报告）

### 3.1 准备
1. 打开 `docs/Release Acceptance.md`，通读一遍（尤其 §〇 环境规则、A 表、B 表、D 页）。
2. 复制它为 `docs/acceptance/v<目标版本>.md`（版本号 = 该阶段确定要发布的版本）。尚未确定目标版本时停止本节，不猜版本、不创建 `stage` 报告；先按 §2 留下阶段自检结果并向露露确认版本。
3. 报告顶部加一段**元信息**：执行者（Claude Code + 模型名）、日期、目标 commit SHA、上一正式 tag、执行环境（GitHub Actions / 本机 / 一次性容器）、本次触发原因。

### 3.2 执行 A 表（22 项固定）
- 能自动跑的（A1-A3、A4）：跑，贴证据（Run 号 / 输出尾行）。
- 能在一次性容器里做的（A5-A7、A9-A11、A17-A21）：起 `docker compose -p kiwi-acc` + 独立卷，按清单"执行方式"做，贴证据。**A10-A18 用能捕获请求的模拟上游**（判断注入以"网关实际发出的请求里有没有"为准，不以模型回答为准）。
- 你在当前环境做不了的（无 Docker、无浏览器、无真实 key）：写 `⏸ BLOCKED` + 缺什么；A22（真实供应商）与需要浏览器/真人观察的项写成 `⏸ BLOCKED（待人工：露露）`，并列出操作步骤。人工证据补齐后才能改为 PASS。
- **A 区不允许填 N/A。**

### 3.3 执行 B 表（按改动追加）
- 先根据本阶段实际改动的文件/模块勾选"本版动了什么"（对照 git log 与 diff，不凭记忆）。
- 勾中的行执行全部追加项；未勾的行整行 N/A 并写"本版未触碰"。

### 3.4 填 D 页裁决
- 如实填每一格。有任何 ❌ 或 ⏸ → 验收结论只能写"**阻塞发布**"或"**待人工补齐后再裁**"。
- "露露裁决"一格**留空**——那是露露的章，你不代填。

### 3.5 交付
- 报告文件进同一个 PR（或单独 `docs: acceptance report vX.Y.Z` 提交）。
- 交付说明里给三行：报告路径；A/B 通过计数与 BLOCKED/待人工清单；你认为的验收结论。
- **不要**因为报告有红项就不交——红项本身就是产出。

---

## 4. 报告写法约束

- 每项四格齐全：执行方式 / 通过标准 / 证据 / 结论（✅ PASS · ❌ FAIL · ⏸ BLOCKED · N/A 仅 B 区）。
- 证据要能被人复核：Run 号、命令与输出尾行、SQL 与结果、捕获请求摘要。"跑过了"不算。
- **不得**出现真实密钥、完整消息正文、DSN。测试用密钥用 `KIWI_ACCEPTANCE_SECRET_<随机串>`，报告里只写"哨兵串零命中"。
- 一个版本只保留一份报告。验收后目标 commit 改变时，在原报告底部追加带日期、旧 SHA、新 SHA 的"复验"节，保留旧证据与旧结论，重跑受影响项目及其依赖项，再更新最终裁决。不得覆盖旧证据，也不得为同一版本另建 `final`、`new` 等随意命名的报告。

---

## 5. 仓库定位（帮你少走弯路）

- 版本单一事实源：`main.py` 顶部 `VERSION`（FastAPI `version=` 硬编码为已知债 REL-01，勿以它为准）。
- 守卫总数以 `scripts/test_kiwi_safety_sync.py` 尾行 `PASS: N total permanent behavior guards` 为准（清单写就时 107，只增不减）。
- compose 服务名 `kiwi-mem`（网关）与 `db`；日志看 `docker compose -p kiwi-acc logs kiwi-mem`。
- 升级脚本 `scripts/update.sh`（默认追 main、有 `--no-backup`；老版本 tag 里可能没有此脚本，升级演练前先确认）。
- 已知问题登记 `KNOWN_ISSUES.md`；发布相关研究稿不在仓库，以 `docs/Release Acceptance.md` 为唯一执行依据。

---

## 6. 你不该做的

- 不代填"露露裁决"。
- 不因环境缺失把 A 区项写成 N/A 或 PASS。
- 不清真实库、不让旧版本连主验收库、不用真实 key 跑 A10-A18。
- 不为了让报告好看而删测试、放宽断言、跳过 B 表勾选。
- 不把本文件当清单用——清单在 `docs/Release Acceptance.md`。

---

*本文件 v1.1 · 2026-08-15 · 与 `docs/Release Acceptance.md` v1.1 配套。v1.1 对齐 `AGENTS.md` 权威关系，修复 PR 自检吞错与真库守卫重复执行风险，冻结版本报告触发条件、一版本一报告和待人工 BLOCKED 语义。清单升版时同步检查本文件的坐标（job 名、服务名、脚本名）是否仍准确。*
