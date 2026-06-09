"""
Anthropic API 格式适配器
将 OpenAI 格式的请求/响应与 Anthropic Messages API 格式互相转换

OpenAI format:    POST /v1/chat/completions
Anthropic format: POST /v1/messages

用法：
  from anthropic_adapter import (
      to_anthropic_request, to_anthropic_headers, get_anthropic_url,
      from_anthropic_response, anthropic_stream_to_openai,
  )
"""

import json
import uuid
from typing import AsyncGenerator


# ============================================================
# 请求转换：OpenAI → Anthropic
# ============================================================

def to_anthropic_request(openai_body: dict) -> dict:
    """将 OpenAI chat/completions 请求体转换为 Anthropic Messages API 格式"""
    messages = list(openai_body.get("messages", []))

    # ── 提取 system message（可能多条，合并） ──
    system_blocks = []
    non_system_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, list):
                # 已经是 content blocks 格式（带 cache_control）
                system_blocks.extend(content)
            elif isinstance(content, str) and content.strip():
                system_blocks.append({"type": "text", "text": content})
        else:
            non_system_messages.append(msg)

    # ── 转换消息列表 ──
    anthropic_messages = _convert_messages(non_system_messages)

    # ── 构建请求体 ──
    body = {
        "model": _strip_model_prefix(openai_body.get("model", "")),
        "messages": anthropic_messages,
        "max_tokens": openai_body.get("max_tokens") or 8192,
    }

    if system_blocks:
        body["system"] = system_blocks

    # 可选参数
    if "temperature" in openai_body:
        body["temperature"] = openai_body["temperature"]
    if "top_p" in openai_body:
        body["top_p"] = openai_body["top_p"]
    if openai_body.get("stream"):
        body["stream"] = True

    # ── tools ──
    if "tools" in openai_body and openai_body["tools"]:
        body["tools"] = _convert_tools_openai_to_anthropic(openai_body["tools"])
        tc = openai_body.get("tool_choice", "auto")
        if tc == "auto":
            body["tool_choice"] = {"type": "auto"}
        elif tc == "none":
            body["tool_choice"] = {"type": "none"}
        elif tc == "required":
            body["tool_choice"] = {"type": "any"}
        elif isinstance(tc, dict) and tc.get("type") == "function":
            # OpenAI 强制指定某个函数：{"type":"function","function":{"name":"..."}}
            # → Anthropic 强制单工具：{"type":"tool","name":"..."}
            # 不转的话 Anthropic 会回退到自动选择，依赖 forced function call 的客户端会拿错工具
            func_name = (tc.get("function") or {}).get("name")
            if func_name:
                body["tool_choice"] = {"type": "tool", "name": func_name}

    # ── 思考链 / extended thinking ──
    reasoning = openai_body.get("reasoning")
    if reasoning and isinstance(reasoning, dict) and reasoning.get("enabled"):
        budget = 10000
        effort = reasoning.get("effort")
        if effort == "low":
            budget = 5000
        elif effort == "high":
            budget = 20000
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        # Anthropic extended thinking 要求 temperature == 1
        body["temperature"] = 1

    return body


def to_anthropic_headers(api_key: str) -> dict:
    """生成 Anthropic API 请求头"""
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def get_anthropic_url(base_url: str) -> str:
    """将 base URL 转换为 Anthropic messages 端点
    
    输入示例：
      https://api.anthropic.com/v1           → .../v1/messages
      https://api.anthropic.com/v1/messages  → 不变
      https://xxx.com/v1/chat/completions    → .../v1/messages
      https://xxx.com                        → .../v1/messages
    """
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


# ============================================================
# 响应转换：Anthropic → OpenAI（非流式）
# ============================================================

def from_anthropic_response(anthropic_data: dict, model: str = "") -> dict:
    """将 Anthropic Messages API 响应转换为 OpenAI chat/completions 格式"""

    # ── 错误处理 ──
    if anthropic_data.get("type") == "error" or "error" in anthropic_data:
        err = anthropic_data.get("error", {})
        return {
            "error": {
                "message": err.get("message", str(anthropic_data)),
                "type": err.get("type", "api_error"),
            }
        }

    content_blocks = anthropic_data.get("content", [])

    # 拆解 content blocks
    text_parts = []
    tool_calls = []
    reasoning_parts = []

    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "thinking":
            reasoning_parts.append(block.get("thinking", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                },
            })

    full_text = "\n".join(text_parts) if text_parts else ""

    # ── message ──
    message = {"role": "assistant", "content": full_text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if reasoning_parts:
        message["reasoning_content"] = "\n".join(reasoning_parts)

    # ── usage ──
    au = anthropic_data.get("usage", {})
    input_tokens = au.get("input_tokens", 0)
    output_tokens = au.get("output_tokens", 0)
    usage = {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    cache_creation = au.get("cache_creation_input_tokens", 0)
    cache_read = au.get("cache_read_input_tokens", 0)
    if cache_creation or cache_read:
        usage["prompt_tokens_details"] = {
            "cached_tokens": cache_read,
            "cache_write_tokens": cache_creation,
        }

    # ── stop reason ──
    stop_reason = anthropic_data.get("stop_reason", "end_turn")
    finish_map = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "stop_sequence": "stop",
    }

    return {
        "id": f"chatcmpl-{anthropic_data.get('id', uuid.uuid4().hex[:12])}",
        "object": "chat.completion",
        "model": model or anthropic_data.get("model", ""),
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_map.get(stop_reason, "stop"),
            }
        ],
        "usage": usage,
    }


# ============================================================
# 流式转换：Anthropic SSE → OpenAI SSE
# ============================================================

async def anthropic_stream_to_openai(response, model: str = "") -> AsyncGenerator[bytes, None]:
    """将 Anthropic SSE 流转换为 OpenAI SSE 格式的 bytes 流

    Anthropic 事件类型：
      message_start → content_block_start → content_block_delta → content_block_stop
      → message_delta → message_stop

    转换为 OpenAI 格式：
      data: {"choices": [{"delta": {...}}]}
      data: [DONE]
    """
    msg_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    buffer = ""
    input_tokens = 0
    output_tokens = 0
    cache_creation = 0
    cache_read = 0

    async for chunk in response.aiter_bytes(chunk_size=256):
        buffer += chunk.decode("utf-8", errors="ignore")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()

            if not line or line.startswith(":") or line.startswith("event:"):
                continue
            if not line.startswith("data: "):
                continue

            raw = line[6:].strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")

            # ── message_start ──
            if event_type == "message_start":
                msg = data.get("message", {})
                model = model or msg.get("model", "")
                u = msg.get("usage", {})
                input_tokens = u.get("input_tokens", 0)
                cache_creation = u.get("cache_creation_input_tokens", 0)
                cache_read = u.get("cache_read_input_tokens", 0)
                yield _sse(msg_id, model, {"role": "assistant"})

            # ── content_block_start ──
            elif event_type == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    yield _sse(msg_id, model, {
                        "tool_calls": [{
                            "index": data.get("index", 0),
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {"name": block.get("name", ""), "arguments": ""},
                        }]
                    })

            # ── content_block_delta ──
            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                dtype = delta.get("type", "")

                if dtype == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield _sse(msg_id, model, {"content": text})

                elif dtype == "thinking_delta":
                    thinking = delta.get("thinking", "")
                    if thinking:
                        yield _sse(msg_id, model, {"reasoning_content": thinking})

                elif dtype == "input_json_delta":
                    partial = delta.get("partial_json", "")
                    if partial:
                        yield _sse(msg_id, model, {
                            "tool_calls": [{
                                "index": data.get("index", 0),
                                "function": {"arguments": partial},
                            }]
                        })

            # ── message_delta (含 stop_reason 和 output usage) ──
            elif event_type == "message_delta":
                d = data.get("delta", {})
                stop = d.get("stop_reason", "end_turn")
                u = data.get("usage", {})
                output_tokens = u.get("output_tokens", 0)

                finish_map = {"end_turn": "stop", "max_tokens": "length",
                              "tool_use": "tool_calls", "stop_sequence": "stop"}

                usage = {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
                if cache_creation or cache_read:
                    usage["prompt_tokens_details"] = {
                        "cached_tokens": cache_read,
                        "cache_write_tokens": cache_creation,
                    }

                payload = {
                    "id": msg_id, "object": "chat.completion.chunk", "model": model,
                    "choices": [{"index": 0, "delta": {},
                                 "finish_reason": finish_map.get(stop, "stop")}],
                    "usage": usage,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()

            # ── message_stop ──
            elif event_type == "message_stop":
                yield b"data: [DONE]\n\n"

            # ── error ──
            elif event_type == "error":
                err_msg = data.get("error", {}).get("message", "Unknown error")
                yield _sse(msg_id, model, {"content": f"⚠️ {err_msg}"})
                yield b"data: [DONE]\n\n"


# ============================================================
# 内部工具函数
# ============================================================

def _strip_model_prefix(model: str) -> str:
    """去掉 OpenRouter 风格前缀：anthropic/claude-sonnet-4 → claude-sonnet-4"""
    return model.split("/", 1)[1] if "/" in model else model


def _convert_tools_openai_to_anthropic(openai_tools: list) -> list:
    """OpenAI tools → Anthropic tools"""
    result = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            func = tool["function"]
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            result.append(tool)  # 可能已经是 Anthropic 格式
    return result


def _convert_messages(openai_msgs: list) -> list:
    """将 OpenAI 格式的消息列表转换为 Anthropic 格式
    
    主要差异：
    - OpenAI tool result: {"role": "tool", "tool_call_id": "...", "content": "..."}
    - Anthropic tool result: {"role": "user", "content": [{"type": "tool_result", ...}]}
    - OpenAI assistant with tool_calls: message.tool_calls 数组
    - Anthropic assistant with tool_use: content 里包含 tool_use blocks
    """
    result = []

    for msg in openai_msgs:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "tool":
            # ── tool result → 合并到 user message ──
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            }
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})

        elif role == "assistant":
            blocks = []

            # 文本内容
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks.extend(content)

            # tool_calls → tool_use blocks
            for tc in msg.get("tool_calls", []):
                func = tc.get("function", {})
                args = func.get("arguments", "{}")
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
                    "name": func.get("name", ""),
                    "input": json.loads(args) if isinstance(args, str) else args,
                })

            if blocks:
                result.append({"role": "assistant", "content": blocks})
            elif content:
                result.append({"role": "assistant", "content": content})

        else:
            # user 等其他角色
            result.append({"role": role, "content": content})

    return result


def _sse(msg_id: str, model: str, delta: dict) -> bytes:
    """构建 OpenAI SSE 格式的一行"""
    payload = {
        "id": msg_id, "object": "chat.completion.chunk", "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
