# Release acceptance records

本目录保存 kiwi-mem 每个发布候选版本的实际验收记录。

- 母版：[`../Release Acceptance.md`](../Release%20Acceptance.md)
- 文件名：`vX.Y.Z.md`，例如 `v1.7.0.md`
- 每个报告必须记录目标版本、目标 commit、上一正式版本、实际执行结果、脱敏证据和最终裁决。
- `PASS` 必须有执行证据；`FAIL`、`BLOCKED` 或未执行的固定项目会阻塞发布；`N/A` 只用于母版 B 区确实未触碰的模块。
- 报告不得包含 API key、DSN、完整私密消息、完整 prompt 或用户标识。使用 CI 链接、命令摘要、SQL 摘要、脱敏截图和唯一哨兵证明。
- 一个版本对应一个报告。目标 commit 改变后必须重跑受影响的检查并更新证据，不得沿用旧 commit 的通过结论。

只有形成明确发布候选版本，或维护者要求执行完整发布验收时，才在这里创建版本报告。普通 PR 和中间阶段的测试结果保留在对应 PR 交付记录中。
