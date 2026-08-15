# CLAUDE.md — kiwi-mem 施工与验收守则（给 Claude Code 看）

你在这个仓库里施工时，除了完成任务本身，还要按本文件执行**阶段验收**并留下**可追溯的报告**。本文件是规矩，不是建议；不清楚时按最保守的一档做，并在报告里写明。

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
| **一个阶段收口**（露露/任务说明里明确说"阶段验收"、"准备发版"、"跑 Release Acceptance"、或版本号被改动） | 跑 §3「阶段验收」——按清单逐项执行，**产出报告** `docs/acceptance/vX.Y.Z.md` |
| 不确定属于哪种 | 按 PR 级自检做，并在交付说明里问一句"要不要跑阶段验收" |

---

## 2. PR 级自检（每票必做，最小集）

```bash
python -m compileall -q .                       # 语法
git diff --check                                 # 空白/行尾
# 12 套既有回归（逐个跑，全部 exit 0）
for t in scripts/test_*.py; do python "$t" || echo "FAIL $t"; done
node scripts/test_calendar_period_defaults.mjs
# 真库守卫（需要本机 PostgreSQL 16；没有则依赖 CI 结果并在交付里注明）
KIWI_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  python scripts/test_kiwi_safety_sync.py
```

守卫脚本会自己建/删一次性数据库，不会碰 DSN 指向之外的库；它**拒绝**没有 `KIWI_TEST_DATABASE_URL` 时回退，别绕。

CI 上对应：`syntax-check` job；`behavior-tests` job 的"运行既有开源回归脚本"与"运行 S1-S6 永久真库行为守卫"两个步骤。交付时给 Run 号。

---

## 3. 阶段验收（产出报告）

### 3.1 准备
1. 打开 `docs/Release Acceptance.md`，通读一遍（尤其 §〇 环境规则、A 表、B 表、D 页）。
2. 复制它为 `docs/acceptance/v<目标版本>.md`（版本号 = 该阶段要发的版本；若尚未定版本，用 `v<当前 VERSION>-stage-<日期>.md`，报告里注明"版本待定"）。
3. 报告顶部加一段**元信息**：执行者（Claude Code + 模型名）、日期、目标 commit SHA、上一正式 tag、执行环境（GitHub Actions / 本机 / 一次性容器）、本次触发原因。

### 3.2 执行 A 表（22 项固定）
- 能自动跑的（A1-A3、A4）：跑，贴证据（Run 号 / 输出尾行）。
- 能在一次性容器里做的（A5-A7、A9-A11、A17-A21）：起 `docker compose -p kiwi-acc` + 独立卷，按清单"执行方式"做，贴证据。**A10-A18 用能捕获请求的模拟上游**（判断注入以"网关实际发出的请求里有没有"为准，不以模型回答为准）。
- 你在当前环境做不了的（无 Docker、无浏览器、无真实 key）：写 `⏸ BLOCKED` + 缺什么；A22（真实供应商）与需要浏览器/真人观察的项默认写"**待人工：露露**"并列出操作步骤。
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
- 报告只增不改：验收后又改了代码，**新起一份**报告（或在原报告底部追加"复验"节并注明新 commit），不覆盖旧结论。

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

*本文件 v1.0 · 2026-08-15 · 与 `docs/Release Acceptance.md` v1.1 配套。清单升版时同步检查本文件的坐标（job 名、服务名、脚本名）是否仍准确。*
