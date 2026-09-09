# KIWI-PREP-01 P1 · 2026-09-09

依据：9/9《爹爹验收 v1》P1 裁决；基线 PR #81 `cf8a2b14f4308722f313af573a68cf6cd7637ffe`。本补丁说明优先于阶段 B 文档中已被裁决改写的 T-11 / T-12 与 K-PREP-21 口径。

状态：P1 施工交付，PR 仍 Draft，停下交独立验收，未合并或部署。

## 改动与红证

- **B-2**：无 Python / jq 时，从 `.env` 最后一条 PORT 配置按数据读取端口，支持行首空白及 CRLF；仅接受 1～65535 的十进制端口，否则保留 8080。没有执行 `.env`。宿主矩阵新增“两个助手均缺失”下 9090 / 非法值两臂，检查实际首页探针 URL。
- **B-5**：T-11 改查 AST 中恰好两个 FastMCP 构造、无保护参数，并检查 `mcp_server.py` 无保护接线词；不再钉死整个文件 blob。T-12 允许合法 `security.py` 存在，继续检查生产代码不导入、不接入 MCP 保护。
- **B-1**：宿主矩阵先断言模块接缝存在，再导入并断言校验函数可调用。缺模块以 AssertionError 报告，不先抛 ImportError。
- **B-3**：`main.py` 的 mcp_access import 移到 anthropic_adapter import 之后，版本注释紧邻 VERSION。

tests-only `d9929a1`：CI [34353181880](https://github.com/LucieEveille/kiwi-mem/actions/runs/34353181880) 先保留旧实现，13 套回归与 PG 通过，新臂恰 1 FAIL、0 ERROR：

```text
AssertionError: Lists differ: ['http://127.0.0.1:8080/'] != ['http://127.0.0.1:9090/']
```

实现提交 `2514e4d`：CI [34353501608](https://github.com/LucieEveille/kiwi-mem/actions/runs/34353501608) 两个 job 全绿，13 套回归、178 条 PG16 守卫、12 个应用 / 脚本方法（Linux 无 skip）、框架兼容与镜像构建通过；pip check 无冲突，audit 恰三个已批准 ID（四条原始记录中一条重复）。

B-1 另以受控缺模块探针调用宿主矩阵入口，确认缺接缝立即抛 AssertionError；这是受控接缝验证，不冒称重放了整套旧依赖环境。

## 变异与指纹

K-PREP-21 现在向 Memory Garden 的 FastMCP 构造加入 `transport_security=None`，要求 T-11 红。新增 K-PREP-23 丢弃无助手端口回退赋值，要求宿主矩阵的 9090 臂红。

实际总数是 **23 个编号、24 次执行**：原 22 个编号新增 23，K-PREP-2 仍有 stdout / logging 两次。裁决中“24 刀 / 25 次”为计数笔误，本票不虚增编号。

账本继续锁相同 16 个 source_blobs，head 指被测实现提交；文书入仓后逐个核对 PR 顶。原 audit 证据文件不改，CI 仍会重跑扫描并验证恰三个已批准 MCP 公告；没有新增风险例外。

实际结果：24 次全部 RED，preflight=0、restored=0。两处新红因原文：

```text
K-PREP-21: 'transport_security' unexpectedly found in ['stateless_http', 'transport_security']
K-PREP-23: Lists differ: ['http://127.0.0.1:8080/'] != ['http://127.0.0.1:9090/']
```

## 临时集成树检查

本地以 `release/kiwi-sync e5a0726` 合成 P1 实现 `2514e4d`，不推送。唯一冲突是 `KNOWN_ISSUES.md`，保留 SEC 段在前、PREP 段在后，其他文件自动合并。暂存树 `2554fc8cf336654ce62015f02b633064f1d9dcfb`（尚不含本 P1 文档和重出账本）。

本地合成树：PREP 12 个方法中 11 OK、Linux PATH 矩阵 1 skip，T-11 / T-12 均通过；SEC-01a 37 OK；`test_admin_secrets.mjs` PASS。Windows 不具备独立 PG16 / Docker；不能把本地的 skip 写成真库或 Linux 宿主证据。独立验收仍须重跑最终临时集成树的 PREP、SEC-01a 及 184 条 PG 守卫、41 刀；不以阶段 B 的旧预演替代 P1 验收。

## 范围与记档

PR 增量只含：`scripts/update.sh`、`main.py`、`scripts/test_kiwi_prep_01.py`、`scripts/kiwi_prep_01_knives.py`、原刀账 JSON、本说明。其余文件保留。

B-4 按裁决仅记档：CI 显式检出 PR head，不能代替与 base 合成后的验证；RELEASE-01 评估是否继续保留。观察失败后最多延迟 60 秒再写、非法恢复态可能残留状态文件、恢复态原参数保存但不重做询问 / 备份，均按本次裁决保留。

下一步：Fable 重放验收①和②，再交 CC；Ready / 合并 / tag / 部署仍待授权。
