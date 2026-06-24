"""
纯函数行为测试（无需数据库 / 不联网）。

专门守护那类「读代码看不出、实跑才暴露」的逻辑：

  1. anthropic_adapter.to_anthropic_request 的 extended thinking 约束
     —— Anthropic 硬性要求 budget_tokens < max_tokens，否则请求被 API 直接 400。
        这是 PR review 实测发现的阻断点，必须有回归守护。

  2. database.detect_contradictions 的矛盾检测
     —— 保护逻辑（手动 / 锁定记忆不自动失效）+ similarity 缺失（关键词命中 /
        embedding 降级）时的字符重叠兜底。

运行：python tests/test_logic.py   （退出码非 0 表示有用例失败）
CI 在装好依赖后运行本文件。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anthropic_adapter import to_anthropic_request
from database import detect_contradictions

_failures = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        _failures.append(name)


# ============================================================
# 1. to_anthropic_request：思考链 budget < max_tokens
# ============================================================
def _req(reasoning=None, max_tokens=None):
    body = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}
    if reasoning is not None:
        body["reasoning"] = reasoning
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return to_anthropic_request(body)


print("== to_anthropic_request：extended thinking 约束 ==")

b = _req({"enabled": True})
check("默认 effort：budget < max_tokens", b["thinking"]["budget_tokens"] < b["max_tokens"])

b = _req({"enabled": True, "effort": "low"})
check("low effort：budget < max_tokens", b["thinking"]["budget_tokens"] < b["max_tokens"])

b = _req({"enabled": True, "effort": "high"})
check("high effort：budget < max_tokens", b["thinking"]["budget_tokens"] < b["max_tokens"])

b = _req({"enabled": True, "effort": "high"}, max_tokens=40000)
check("显式大 max_tokens 不被压低", b["max_tokens"] == 40000 and b["thinking"]["budget_tokens"] < b["max_tokens"])

b = _req()
check("无 reasoning 时不生成 thinking", "thinking" not in b)

b = _req({"enabled": False})
check("reasoning.enabled=False 时不生成 thinking", "thinking" not in b)


# ============================================================
# 2. detect_contradictions：保护逻辑 + similarity 兜底
# ============================================================
def mem(id, title, content, similarity=0, source="extracted", is_permanent=False):
    return {"id": id, "title": title, "content": content,
            "similarity": similarity, "source": source, "is_permanent": is_permanent}


print("== detect_contradictions：保护逻辑 + similarity 兜底 ==")

# 基础：标题相同、向量相似度 0.6（相关但不同）→ 判为疑似矛盾
res = detect_contradictions("工作单位", "我现在在阿里巴巴工作",
                            [mem(1, "工作单位", "我现在在腾讯工作", similarity=0.6)])
check("中等相似度的更新被判为矛盾", 1 in res)

# 保护：手动录入（user_explicit）永不自动失效
res = detect_contradictions("工作单位", "我现在在阿里巴巴工作",
                            [mem(2, "工作单位", "我现在在腾讯工作", similarity=0.6, source="user_explicit")])
check("手动记忆(user_explicit)不被标矛盾", 2 not in res)

# 保护：锁定记忆（is_permanent）永不自动失效
res = detect_contradictions("工作单位", "我现在在阿里巴巴工作",
                            [mem(3, "工作单位", "我现在在腾讯工作", similarity=0.6, is_permanent=True)])
check("锁定记忆(is_permanent)不被标矛盾", 3 not in res)

# 兜底修复：关键词路径 similarity=0，但内容字符重叠为中等 → 仍能检出矛盾
res = detect_contradictions("工作单位", "我现在在阿里巴巴上班工作",
                            [mem(4, "工作单位", "我现在在腾讯公司上班工作", similarity=0)])
check("similarity=0 时靠字符重叠兜底仍能检出矛盾", 4 in res)

# 边界：内容完全无关 → 不判矛盾（即使标题相同）
res = detect_contradictions("工作单位", "我现在在阿里巴巴上班工作",
                            [mem(5, "工作单位", "今天天气很好出去散步看电影", similarity=0)])
check("内容无关时不判矛盾", 5 not in res)

# 边界：近乎重复（向量 0.95 > 0.85）→ 交给去重处理，不判矛盾
res = detect_contradictions("工作单位", "我现在在阿里巴巴工作",
                            [mem(6, "工作单位", "我现在在阿里巴巴工作", similarity=0.95)])
check("近重复(>0.85)不判矛盾(交给去重)", 6 not in res)

# 已知残余风险（仅打印提醒，不作失败断言）：纯数字/单字更新且整句几乎相同时，
# 字符重叠会算成近重复而漏判。详见 KNOWN_ISSUES.md（中危第二批后续项）。
res = detect_contradictions("女儿年龄", "我女儿今年六岁",
                            [mem(7, "女儿年龄", "我女儿今年五岁", similarity=0)])
print(f"  [INFO] 已知残余：纯数字/单字更新可能漏判（当前 7 in res = {7 in res}），见 KNOWN_ISSUES.md")


# ============================================================
# 3. prepare_background_request：归因头必须 ASCII 安全
#    含 É(\xc9) 等非 ASCII 的 X-Title 会让 httpx 编码直接抛 'ascii' codec can't
#    encode，把整个后台请求带崩。kiwi 各处 title 本就是 ASCII，这里守护清洗逻辑本身。
# ============================================================
from anthropic_adapter import prepare_background_request


def _headers_ascii_safe(headers):
    try:
        for v in headers.values():
            v.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


h, _ = prepare_background_request("sk-x", "openai", {"model": "m"},
                                  referer="https://gateway.eveille.love",
                                  title="Éveille Memory Extraction")
check("含 É 的 X-Title 被清洗成 ASCII（不再让 httpx 编码崩溃）", _headers_ascii_safe(h))
check("清洗后 X-Title 仍非空（保留可读标识）", bool(h.get("X-Title")))

h2, _ = prepare_background_request("sk-x", "openai", {"model": "m"}, title="未命名场景")
check("纯非 ASCII 标题清洗后回退占位符", _headers_ascii_safe(h2) and h2.get("X-Title") == "Eveille")


# ============================================================
if _failures:
    print(f"\n❌ {len(_failures)} 个用例失败：{_failures}")
    sys.exit(1)
print("\n✅ 全部用例通过")
