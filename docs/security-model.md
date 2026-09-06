# Kiwi-Mem 安全模型与凭据边界

本章记录 KIWI-SEC-01a 的公版行为（2026-09-07 P2 补丁更新）。Kiwi-Mem 默认没有认证，环境变量回落和默认上游地址仍然保留。

## 部署边界

所有能访问服务的人都能访问管理、同步和模型接口。请只面向可信使用者，或用反向代理认证、Cloudflare Access、IP 白名单保护**整个服务**。只挡住管理页面的 HTML 不足以保护管理 API。

能修改供应商地址的人仍能让服务把已有钥匙用于他配置的地址。凭据脱敏和出站地址校验不能替代访问控制。数据库、环境变量和原始数据库备份中的钥匙仍是明文。限制 `.env` 和数据库备份的读取权限，不要把它们提交进仓库。

## 密钥响应与修改

供应商列表、新建、更新共用固定十字段响应：`id`、`name`、`api_base_url`、`api_format`、`enabled`、`created_at`、`updated_at`、`has_credential`、`api_key_last4`、`api_key_preview`。没有 `api_key`。凭据长度至少 12 字符时才显示末四位；较短凭据只显示已配置。`api_key_preview` 是弃用中的兼容别名，仅返回固定遮罩加尾号或配置状态。

`search_api_key` 是 schema 的 `secret` 类型。内部配置读取保留真实值；HTTP 配置读取的 `value` 为空，同时返回 `has_value`、`last4` 和实际生效的 `source`。搜索专用配置接口保留引擎、结果数及布尔兼容别名 `api_key_set`，移除旧的前缀预览 `api_key`。

两个配置 PUT 对 secret 的缺字段、空串、全空白均保持现值，不写库；null 和非字符串返回 400。非空字符串原样存储。通用配置 PUT 的空输入行为因此发生调整，非 secret 项保持原行为。搜索专用 PUT 的 max_results 要求 JSON 整数 1–20（数字字符串会被拒绝），engine 必须是支持的引擎标识或空字符串。

显式 `PUT /admin/config/search_api_key`、`{"clear":true}` 删除数据库覆盖行；若环境变量已有搜索钥匙，删除后它会重新生效。面板按钮明确标为“清除数据库密钥”，不是撤销环境变量中的凭据。不能同时提交 clear 和 value。

供应商新建拒绝非字符串 api_key（含 null，返回 400），字符串仍 strip；供应商更新仍将全空白视为不修改。面板只显示服务端的安全元数据，成功后清空密钥输入；晚到的保存响应不能清掉随后编辑的内容。

## ZIP 导出与旧备份恢复

`GET /sync/export` 在扁平 `config.json` 中保留 secret 键，但值为空。独立 `backup_meta.json` 的格式为 `{"format_version":2,"secrets_configured":["search_api_key"]}`，只记录已配置状态，不记录尾号。

恢复端是 `POST /sync/import-backup`。无 metadata 的旧包仍可导入，包括旧包显式保存的非空密钥。新包的空 secret 不覆盖已有 DB 值，也不新增空行遮住 env。非法或未知 metadata 版本在任何恢复写入前拒绝。旧导入器忽略新增文件，仍可读取新包中的其余数据。

回执 `secrets_requiring_input` 只列出备份标记已配置、但恢复后的目标仍无有效值的 secret 键。供应商表本来就不在此 ZIP 内。本机制只排除 schema 标记的秘密配置，不识别用户自行贴进对话、提示词或其它正文的密钥；原始 SQL 备份仍需要严格保护。

## 出站与失败响应

凭据只用于已配置、通过校验的 HTTP/HTTPS 地址。拒绝 userinfo、协议相对 URL、非法端口、查询串、片段及控制字符（含 DEL）；保留合法路径前缀和显式端口。拒绝带 query/fragment 的配置是兼容变化，应改为不带这些部分的 API base URL。

通用余额地址只对解析后的 path 操作：剥掉 /chat/completions 后缀，末段恰为 v1 才去掉；v1beta、v10 等段保留，scheme/host/port 始终从已验证 origin 构造。原生供应商以精确 hostname 判断。两个 OpenRouter 额度端点从已验证的供应商 origin 构造；代理地址不会因为路径中含 openrouter 而收到原生分流。带凭据的相关请求不跟随重定向。通用额度接口的 404 可表示“不支持额度查询”，其它失败给稳定错误。余额聚合接口逐供应商隔离失败：仍返回 HTTP 200，失败条目只保留供应商身份和 error_code，继续查询其余供应商；env 回落同样返回条目错误。读取供应商列表等端点级内部故障仍返回 500。

本票收口供应商、配置、搜索测试、嵌入、ZIP 导入导出，以及日历/整理/画像和 Dream 中关联的 HTTP 错误出口。HTTP 失败给稳定 `error` / `error_code`，不返回异常原文或上游错误正文。日志只记受控事件与错误分类。输入校验维持 400，资源不存在 404，内部失败 500，上游失败 502。

SSE 已建流后用错误帧结束，`[DONE]` 恰一次；错误不作为助手正文保存。上游 HTTP 200 但返回非 SSE 原文时，事件循环与尾块都拒绝透传，以 parse_failed 错误帧结束；不依据 Content-Type 判定，保留 data/event/id/retry 和注释行。带 error:null 的正常帧继续通过，非空 error 或 type:error 才表示失败。SSE 上游 HTTP 错误体不读取、不缓冲。内部 embedding 失败依旧返回 None，批量返回等长 None 列表；聊天搜索仍可降级为空结果，搜索测试通过严格模式区分真正失败。Dream 新失败记录使用稳定码，历史 error 状态记录在公开读取时隐藏旧异常叙事，数据库原记录不被改写。

## 本票之后

尚未完成全仓错误清扫：`main.py` 附录分类中的其余 49 处异常出口、`daily_digest.py` 的 6 处内部错误字典及其它未列入的 MCP/工具错误通道属于后续 KIWI-ERR-01。调用闭包中已在本票 HTTP 边界拦住的错误，不等于其所有内部调用者都已修复。

MCP 的 Host/Origin 配置与精确挂载由后续 BUILD-01/SEC-01b 交付，本票不宣称它们已经启用。向量身份、重新对齐和面板重建按钮属于 EMB-01。无认证、env 回落和默认地址属于公版设计选择，始终需要上述部署边界。
