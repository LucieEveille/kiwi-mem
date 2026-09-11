# KIWI-BUILD-01 阶段 A：tests-only 红证

日期：2026-09-10。施工依据：指令书 v1.1 及用户同轮裁决。状态：阶段 A 交付，等待验收；阶段 B 未开始。

## 基线与范围

- PR #82，Draft，base `release/kiwi-sync`。
- 实现基线 `6b2b43d0b746fb9c69f52f54d0347bd63e3ae9f4`，tree `619b7518b1865a7067c21e170d515d9bf1257a2e`。
- 被测 tests-only head `78ecf8eb22ee7b25409822ba778eb02a993e99f1`；后续证据提交只增加本报告与 evidence 文件。账本的四个 source_blobs 锁定被测文件。
- 应用代码、requirements.txt、Dockerfile、部署配置均未改。四个施工文件为新增 BUILD 守卫、刀目录、PREP 守卫反转、CI 接线。

## 红证与回归

[CI run 34453369839](https://github.com/LucieEveille/kiwi-mem/actions/runs/34453369839) 在上述 head 完整跑过：

| 检查 | 结果 |
| --- | --- |
| Python 语法 | 通过 |
| SEC-01a | 37 通过 |
| 既有回归脚本与 Node 检查 | 通过 |
| PG16 永久守卫 | 184 通过 |
| PREP 应用套件 | 13 组，六条授权反转守卫产生 7 处 assertion failure，0 ERROR |
| BUILD | 13 组，13 处 assertion failure，0 ERROR |

CI 总状态为 failure，符合 tests-first 阶段。框架兼容/镜像及 PREP 刀与扫描后续步骤因红证跳过，不能宣称本轮全部 CI 通过。CI 安装命令临时将旧 MCP 约束为 1.12.4，避免旧 requirements 的无上界范围引入无关红点；阶段 B 应移除临时约束并使用应用精确 pin。

本地 BUILD 同为 13 failures / 0 errors。PREP 六条单独运行共 7 failures / 0 errors。SEC 37 与框架兼容通过；本地工具流回归缺 PostgreSQL，已由本次 CI 的真实一次性 PG16 路径通过，未将本地阻塞当作产品失败。

## 守卫范围与夹具

BUILD T-01～13 覆盖依赖及镜像、配置与两构造器、Host、Origin、Content-Type、六处日志/回包哨兵、IP scope 副本与并发隔离、九键状态、启动摘要、接线、streamable HTTP/SSE 客户端、SDK 第二层与 filter、部署配置/探针。

PREP 仅按指令反转 T-01/02/03/05/11/12；两个夹具 helper 与默认 Host 跟随调整。T-06～10、T-13 和 fallback 方法原文不变；PG 观察臂仍通过。独立 JSON 账本列明方法与红因。

夹具使用假数据库和假上游，不访问生产。测试内的真实 SDK 应用与本地 socket 客户端路径为阶段 B 绿证准备；当前旧实现多数在缺失 builder/guard 等接口时即断言失败，后面的行为矩阵尚未走到，不能据此声称所有行为臂已经实跑。T-13 的配置值为构造的渲染结果，不能当作真实 Compose 部署证明；脚本回滚夹具为 Linux 条件路径，阶段 B 须完成对应绿证。没有真实供应商请求。

## 刀目录与依赖预检

刀目录共 23 个编号，`--list` 可运行；本阶段没有施刀，执行数为 0。阶段 B 才补锚点、施刀与还原账本，不能将目录称为 23 刀全红。

仓外 Python 3.12 隔离环境试装目标组合 mcp 1.29.1 / httpx 0.27.2 / uvicorn 0.31.1，pip check 无冲突。OSV pip-audit 对解析出的 40 项依赖返回零漏洞，原始 JSON 与解析列表见 evidence。此为 Windows 目标依赖预检；未升级应用，未替代阶段 B 的运行、镜像及最终扫描验收。

## 下一步

等待阶段 A diff 验收后实施阶段 B。尚未接入任何访问保护、未执行变异刀、未合并、未部署。桌面总纲 v1.6.1 未找到实体文件，本阶段依据用户明确裁决与 v1.1 指令书；不擅自重写冻结总纲。
