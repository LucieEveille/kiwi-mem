"""
记忆提取模块 —— 用 LLM 从对话中提炼关键记忆
=============================================
每次对话结束后，把最近的对话内容发给一个便宜的模型，
让它提取出值得记住的信息，存到数据库里。

v2.3 改进：提取时注入已有记忆，让模型对比后只提取全新信息。
"""

import os
import json
import httpx
from typing import List, Dict

API_KEY = os.getenv("MEMORY_API_KEY", "") or os.getenv("API_KEY", "")
_RAW_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "") or os.getenv("API_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")

# 确保 URL 以 /chat/completions 结尾
API_BASE_URL = _RAW_BASE_URL if _RAW_BASE_URL.rstrip("/").endswith("/chat/completions") else f"{_RAW_BASE_URL.rstrip('/')}/chat/completions"

# 用来提取记忆的模型（便宜的就行）
MEMORY_MODEL = os.getenv("MEMORY_MODEL", "anthropic/claude-haiku-4")


EXTRACTION_PROMPT = """你是信息提取专家，负责从对话中识别并提取值得长期记住的关键信息。

# 提取重点
- 关键信息：仅提取用户的重要信息，忽略日常琐事
- 重要事件：记忆深刻的互动，需包含人物、时间、地点（如有）

# 提取范围
- 个人：年龄、生日、职业、学历、居住地
- 偏好：明确表达的喜好或厌恶
- 健康：身体状况、过敏史、饮食禁忌
- 事件：与AI的重要互动、约定、里程碑
- 关系：家人、朋友、重要同事
- 价值观：表达的信念或长期目标
- 情感：重要的情感时刻或关系里程碑

{emotion_instruction}

# 不要提取
- 日常寒暄（"你好""在吗"）
- AI助手自己的回复内容
- 关于记忆系统本身的讨论（"某条记忆没有被记录""记忆遗漏""没有被提取"等）
- 技术调试、bug修复的过程性讨论（除非涉及用户技能或项目里程碑）
- AI的思考过程、思维链内容

# 已知信息处理【最重要】
<已知信息>
{existing_memories}
</已知信息>

- 新信息必须与已知信息逐条比对
- 相同、相似或语义重复的信息必须忽略（例如已知"用户去妈妈家吃团年饭"，就不要再提取"用户春节去了妈妈家"）
- 已知信息的补充或更新可以提取（例如已知"用户养了一只猫"，新信息"猫最近生病了"可以提取）
- 与已知信息矛盾的新信息可以提取（标注为更新）
- 仅提取完全新增且不与已知信息重复的内容
- 如果对话中没有任何新信息，返回空数组 []

# 可用的分类列表
{categories_list}

# 输出格式
请用以下 JSON 格式返回（不要包含其他内容）：
[
  {"title": "简短标题", "content": "记忆内容", "importance": 分数, "emotional_weight": 情绪浓度, "category": "分类名"},
  {"title": "简短标题", "content": "记忆内容", "importance": 分数, "emotional_weight": 情绪浓度, "category": "分类名"}
]

字段说明：
- title: 用4-10个字概括这条记忆的主题（如"饮食偏好""用药方案""情感里程碑"）
- content: 记忆的具体内容
- importance: 信息重要度 1-10，10 最重要
- emotional_weight: 情绪浓度 0-10，0=无情绪，10=极强情绪。判断标准是对话时双方的情绪强度，不是信息重要性
- category: 从上面的分类列表中选择最合适的一个，如果都不合适就填空字符串 ""
如果没有值得记住的新信息，返回空数组：[]
"""

# 高情绪时追加的提取指引
EMOTION_HIGH_INSTRUCTION = """# 🩷 情绪锚点提取【本轮对话情绪浓度高，请特别注意】
本轮对话被检测到情绪浓度较高。除了信息性记忆外，还要识别以下内容：
- 用户表达了强烈情绪的时刻（哭泣、崩溃、特别开心、深层信任、脆弱袒露）
- AI的回应让用户情绪发生明显变化的时刻
- 即使没有"新信息"，只要情绪浓度高，也值得提取
- 这类记忆的 emotional_weight 应为 6-10"""

EMOTION_NORMAL_INSTRUCTION = ""


async def extract_memories(messages: List[Dict[str, str]], existing_memories: List[str] = None, categories: List[str] = None, model_override: str = None, prompt_override: str = None, emotion_level: str = "normal") -> List[Dict]:
    """
    从对话消息中提取记忆

    参数：
        messages: 对话消息列表，格式 [{"role": "user", "content": "..."}, ...]
        existing_memories: 已有记忆内容列表，用于去重对比
        categories: 可用的分类名称列表，用于自动归类
        model_override: 覆盖默认提取模型（从数据库配置传入）
        prompt_override: 覆盖默认提取提示词（从数据库配置传入）
        emotion_level: 本轮对话的情绪级别（'high'/'medium'/'normal'），影响提取策略

    返回：
        记忆列表，格式 [{"content": "...", "importance": N, "emotional_weight": N, "category": "..."}, ...]
    """
    if not API_KEY:
        print("⚠️  API_KEY 未设置，跳过记忆提取")
        return []

    if not messages:
        return []

    # 把对话格式化成文本
    conversation_text = ""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role == "user":
            conversation_text += f"用户: {content}\n"
        elif role == "assistant":
            conversation_text += f"AI: {content}\n"

    if not conversation_text.strip():
        return []

    # 格式化已有记忆
    if existing_memories:
        memories_text = "\n".join(f"- {m}" for m in existing_memories)
    else:
        memories_text = "（暂无已知信息）"

    # 格式化分类列表
    if categories:
        categories_text = "、".join(categories)
    else:
        categories_text = "（暂无分类，category 字段填空字符串即可）"

    # 把已有记忆和分类填入prompt（用 replace 而非 format，防止 prompt 里的花括号被误解析）
    base_prompt = prompt_override if prompt_override else EXTRACTION_PROMPT
    
    # 注入情绪指引（v5.2）
    emotion_instruction = EMOTION_HIGH_INSTRUCTION if emotion_level == "high" else EMOTION_NORMAL_INSTRUCTION
    
    prompt = (base_prompt
        .replace("{existing_memories}", memories_text)
        .replace("{categories_list}", categories_text)
        .replace("{emotion_instruction}", emotion_instruction)
    )

    # 确定使用的模型
    use_model = model_override if model_override else MEMORY_MODEL

    # v5.4：动态解析供应商端点（优先走数据库 provider，降级到环境变量）
    try:
        from database import resolve_model_endpoint
        use_api_url, use_api_key, use_api_format = await resolve_model_endpoint(use_model)
    except Exception:
        use_api_url = API_BASE_URL
        use_api_key = API_KEY
        use_api_format = "openai"

    if not use_api_key:
        print("⚠️  无可用 API Key（供应商和环境变量均未配置），跳过记忆提取")
        return []

    # 调用 LLM 提取记忆
    try:
        from anthropic_adapter import prepare_background_request, parse_background_response
        _body = {
            "model": use_model,
            "max_tokens": 1000,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请从以下对话中提取新的记忆：\n\n{conversation_text}"},
            ],
        }
        _headers, _send_body = prepare_background_request(
            use_api_key, use_api_format, _body,
            referer="https://midsummer-gateway.local",
            title="AI Memory Gateway - Memory Extraction",
        )
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(use_api_url, headers=_headers, json=_send_body)

            if response.status_code != 200:
                print(f"⚠️  记忆提取请求失败: {response.status_code}")
                return []

            data = parse_background_response(response.json(), use_api_format)
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # 日志：打印模型原始返回（方便排查）
            print(f"🔍 记忆提取模型返回（前200字）: {text[:200]}...")

            # 清理可能的 markdown 格式
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            # 解析 JSON（正则兜底：从文本中提取 JSON 数组）
            memories = None
            try:
                memories = json.loads(text)
            except json.JSONDecodeError:
                # 兜底：用正则找 [ ... ] 部分
                import re
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    try:
                        memories = json.loads(match.group())
                        print(f"🔧 JSON 正则兜底解析成功")
                    except json.JSONDecodeError:
                        pass
            
            if not memories or not isinstance(memories, list):
                print(f"⚠️  记忆提取返回非数组格式，跳过")
                return []

            # 验证格式
            valid_memories = []
            for mem in memories:
                if isinstance(mem, dict) and "content" in mem:
                    # importance 安全转换：LLM 可能返回浮点、字符串或 null
                    try:
                        imp = int(float(mem.get("importance", 5)))
                        imp = max(1, min(10, imp))
                    except (ValueError, TypeError):
                        imp = 5
                    # emotional_weight 安全转换（v5.2）
                    try:
                        emo = int(float(mem.get("emotional_weight", 0)))
                        emo = max(0, min(10, emo))
                    except (ValueError, TypeError):
                        emo = 0
                    valid_memories.append({
                        "title": str(mem.get("title", "")),
                        "content": str(mem["content"]),
                        "importance": imp,
                        "emotional_weight": emo,
                        "category": str(mem.get("category", "")),
                    })

            print(f"📝 从对话中提取了 {len(valid_memories)} 条新记忆（已对比 {len(existing_memories or [])} 条已有记忆）")
            return valid_memories

    except json.JSONDecodeError as e:
        print(f"⚠️  记忆提取结果解析失败: {e}")
        return []
    except Exception as e:
        print(f"⚠️  记忆提取出错: {e}")
        return []
