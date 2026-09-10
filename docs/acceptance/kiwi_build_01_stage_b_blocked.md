# KIWI-BUILD-01 阶段 B 开工停点：SDK 内部配置对象复制

日期：2026-09-10。PR #82，base release/kiwi-sync。状态：阶段 A 修正完成；阶段 B 已开始但未交付，按指令书 §四-6 合同冲突停工。

## 已完成的阶段 A 修正

Tests-only commit `8f1f84848bb58d864482401cc7d85beb8e706298`：T-05 的 APPLICATION/JSON 臂改成 HTTP 415，并断言体不含 invalid_content_type。其余期望不变。旧实现重新运行 BUILD：13 组、13 assertion failures、0 ERROR；账本更新该测试的 source_blob。未把修正与实现混为一个提交。

## 独立复现

环境：Python 3.12，mcp 1.29.1，pydantic 2.13.5，pydantic-settings 2.15.0。独立进程，无 Kiwi import，无 patch：

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
s = TransportSecuritySettings(enable_dns_rebinding_protection=True,
    allowed_hosts=['localhost'], allowed_origins=['http://localhost'])
a = FastMCP('a', stateless_http=True, transport_security=s)
b = FastMCP('b', stateless_http=True, transport_security=s)
# a.settings.transport_security is s: False
# b.settings.transport_security is s: False
# a.settings.transport_security is b.settings.transport_security: False
# a.settings.transport_security == s: True
# b.settings.transport_security == s: True
```

SDK FastMCP 的 Settings 启用了 nested_model_default_partial_update=True（server.py:89），构造器将输入交给 Settings（:206）。本环境实际重建了嵌套配置对象。因此「构造器传入同一个 _SECURITY」已经做到，但守卫要求的「两个 SDK 内部配置与 _SECURITY 为同一对象」仍失败。不是夹具 reload 导致；上面的独立探针足以复现。

本地阶段 B 草稿试跑 13 组，8 failures、0 ERROR，8 处均被该 identity 断言挡住。剩余深层行为臂未执行，不作绿证或完成声明。

## 需要 Fable 的窄裁决

建议允许：两构造器和门卫仍传同一个缓存对象；SDK 内部允许等值副本。T-02 / run_sdk 改为核输入参数 identity、两个内部配置完整 model_dump 相等，并分别核三个对象请求前后不变。K-BUILD-2 仍须用构造参数 identity 捕获「给 calendar 另造一个等值对象」，不能只改成 assertEqual 就丢掉这把刀。

若合同坚持 SDK 内部 identity，则需另授权在两个构造器之后、创建 app 之前显式把 settings.transport_security 绑定回 _SECURITY；这会超出当前「两构造器各加一个关键字」范围。当前未采用该做法，也未修改第三方代码。

## 本地草稿保全与未做

阶段 B 尚未提交的五个应用文件：mcp_access.py / mcp_server.py / main.py / requirements.txt / Dockerfile。草稿保留在当前隔离 checkout，未推送。初次试跑临时借用的 Windows preflight audit 已撤出正式 audit 路径，不能替代阶段 B 干净环境最终扫描。

未完成：深层绿证、PREP 刀重锚、BUILD 23 刀、SEC 41 刀、最终扫描、镜像、文档与 CI 全套。无合并、部署、VPS/Notion 写入。
