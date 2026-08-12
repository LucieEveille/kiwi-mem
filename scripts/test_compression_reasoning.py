"""No-network contracts for compression placeholders and reasoning effort."""

import asyncio
import contextlib
import copy
import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import anthropic_adapter
import config
import database
import main as gateway


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class _FakeConnection:
    def __init__(self):
        self.writes = []

    async def execute(self, *args):
        self.writes.append(args)
        return "INSERT 0 1"


class _FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _FakeAcquire(self.conn)


async def check_reasoning_config_contract():
    conn = _FakeConnection()

    async def fake_pool():
        return _FakePool(conn)

    allowed = ("off", "auto", "low", "medium", "high", "xhigh", "max")
    rejected = ("", "ultra", "HIGH")
    with patch.object(config, "get_pool", fake_pool):
        for value in allowed:
            check(await config.set_config("reasoning_effort", value), f"config must accept {value}")
        accepted_writes = len(conn.writes)
        for value in rejected:
            check(
                not await config.set_config("reasoning_effort", value),
                f"config must reject unsupported reasoning effort {value!r}",
            )
        check(len(conn.writes) == accepted_writes, "rejected config values must never reach the database")

        transport = httpx.ASGITransport(app=gateway.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
            admin_response = await client.put(
                "/admin/config/reasoning_effort",
                json={"value": "ultra"},
            )
            check("error" in admin_response.json(), "admin config must return an explicit invalid-value error")

            sync_response = await client.put(
                "/sync/settings",
                json={"reasoning_effort": "ultra"},
            )
            check(
                sync_response.json().get("rejected") == ["reasoning_effort"],
                "sync settings must report an invalid reasoning value as rejected",
            )

    # 本票范围边界：后端请求合同扩到七档，但管理面板**不扩档**，保持基线五档，
    # 留给后续「思考强度双仓专项票」统一处理（面板扩档牵涉 UI 文案与双仓同步）。
    # 这里锁住基线，避免有人顺手把面板改了却不走那张票。
    panel_source = (ROOT / "admin-panel" / "js" / "config-schema.js").read_text(encoding="utf-8")
    check(
        "options:['off','auto','low','medium','high']" in panel_source,
        "管理面板本票不扩档，reasoning_effort 应保持基线五档",
    )


async def check_request_reasoning_contract():
    for value in config.REASONING_EFFORT_VALUES:
        check(gateway._normalize_reasoning_effort(value) == value, f"request must accept {value}")
    check(gateway._normalize_reasoning_effort(None) is None, "omitted effort must preserve legacy behavior")
    check(gateway._normalize_reasoning_effort(" HIGH ") == "high", "request effort may normalize case/space")
    check(gateway._normalize_reasoning_effort(" MAX ") == "max", "DeepSeek 的 max 同样按大小写/空格规范化")

    for value in ("", "ultra", "higher", 7):
        try:
            gateway._normalize_reasoning_effort(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"request must reject unsupported reasoning effort {value!r}")

    provider_calls = []

    async def forbidden_provider_call(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("invalid reasoning must fail before provider routing")

    transport = httpx.ASGITransport(app=gateway.app)
    with patch.object(gateway, "resolve_provider_for_model", forbidden_provider_call):
        async with httpx.AsyncClient(transport=transport, base_url="http://kiwi.test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "test/model",
                    "messages": [{"role": "user", "content": "reasoning contract"}],
                    "reasoning_effort": "ultra",
                },
            )

    check(response.status_code == 400, "unsupported request effort must return HTTP 400")
    payload = response.json()
    error = payload.get("error", {})
    check(error.get("param") == "reasoning_effort", "400 response must identify reasoning_effort")
    check(
        "/".join(config.REASONING_EFFORT_VALUES) in error.get("message", ""),
        "400 response must list allowed values",
    )
    check(provider_calls == [], "invalid request must not touch provider routing or upstream I/O")

    body = {"reasoning": {"enabled": False}, "reasoning_effort": "stale"}
    gateway._apply_reasoning(body, True, False, "auto")
    check(body == {"reasoning": {"enabled": True}}, "auto must enable OpenRouter reasoning without effort")
    body = {}
    gateway._apply_reasoning(body, False, False, "high")
    check(body == {"reasoning_effort": "high"}, "direct OpenAI-compatible high must remain supported")
    body = {"reasoning": {"enabled": True}, "reasoning_effort": "high"}
    gateway._apply_reasoning(body, True, False, "off")
    check(body == {}, "off must remove every outbound reasoning field")

    # ── 各家值域不同，档位必须按供应商就近降到它的天花板 ──────────────────
    DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
    OPENAI_URL = "https://api.openai.com/v1/chat/completions"
    OR_URL = "https://openrouter.ai/api/v1/chat/completions"

    # DeepSeek 官方认 max：不能降档，否则用户白丢一档（v4-flash 传 xhigh 只到 high）
    for level in config.REASONING_EFFORT_LEVELS:
        body = {}
        gateway._apply_reasoning(body, False, False, level, api_url=DEEPSEEK_URL)
        check(
            body == {"reasoning_effort": level},
            f"DeepSeek 官方必须原样透传 {level}（它的值域到 max）",
        )

    # 中转站代理 DeepSeek：URL 里没有 deepseek，靠模型名认出来
    body = {"model": "deepseek-v4-flash"}
    gateway._apply_reasoning(body, False, False, "max", api_url="https://aihubmix.com/v1/chat/completions")
    check(
        body.get("reasoning_effort") == "max",
        "经中转站访问 DeepSeek 时应按模型名识别，仍保留 max",
    )

    # OpenRouter 统一层最高 xhigh：max 必须就近降级，否则上游直接拒绝
    body = {}
    gateway._apply_reasoning(body, True, False, "max", api_url=OR_URL)
    check(
        body == {"reasoning": {"enabled": True, "effort": "xhigh"}},
        "OpenRouter 无 max，必须就近降级为 xhigh",
    )
    body = {}
    gateway._apply_reasoning(body, True, False, "xhigh", api_url=OR_URL)
    check(
        body == {"reasoning": {"enabled": True, "effort": "xhigh"}},
        "OpenRouter 的 xhigh 是天花板本身，不应被改动",
    )

    # ── 优先级铁律：OpenRouter 判定必须早于 DeepSeek ──────────────────────
    # 若哪天有人把 DeepSeek 分支挪到前面，「OpenRouter 上的 DeepSeek 模型」就会被
    # 误判成可发 max，用户直接吃 400。下面几种形态都必须降到 xhigh。
    for or_model in ("deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-flash", "deepseek-chat"):
        body = {"model": or_model}
        gateway._apply_reasoning(body, True, False, "max", api_url=OR_URL)
        check(
            body.get("reasoning", {}).get("effort") == "xhigh",
            f"经 OpenRouter 调用 {or_model} 时，OR 上限必须优先于 DeepSeek 值域",
        )

    # 更狠一层：即使 is_openrouter 没算准（传 False），URL 仍是 OpenRouter，
    # 也不能因为模型名含 deepseek 就放行 max
    body = {"model": "deepseek/deepseek-v4-pro"}
    gateway._apply_reasoning(body, False, False, "max", api_url=OR_URL)
    check(
        body.get("reasoning_effort") == "xhigh",
        "is_openrouter 判定失效时，OpenRouter URL 仍须兜住上限，不得被 DeepSeek 模型名抢跑",
    )

    # 反向确认优先级函数本身
    check(
        gateway._provider_effort_ceiling(OR_URL, "deepseek/deepseek-v4-pro", True) == "xhigh",
        "① OR + DeepSeek 模型 → 天花板取 OR 的 xhigh",
    )
    check(
        gateway._provider_effort_ceiling(DEEPSEEK_URL, "deepseek-v4-flash", False) == "max",
        "② DeepSeek 直连 → 天花板取 max",
    )
    check(
        gateway._provider_effort_ceiling(OPENAI_URL, "gpt-5.2", False) == "xhigh",
        "③ 其余 OpenAI 兼容 → 天花板取默认 xhigh",
    )

    # 直连 OpenAI：官方值域到 xhigh
    body = {}
    gateway._apply_reasoning(body, False, False, "max", api_url=OPENAI_URL)
    check(
        body == {"reasoning_effort": "xhigh"},
        "直连 OpenAI 时 max 应降到官方值域上限 xhigh",
    )
    for level in ("low", "medium", "high", "xhigh"):
        body = {}
        gateway._apply_reasoning(body, False, False, level, api_url=OPENAI_URL)
        check(
            body == {"reasoning_effort": level},
            f"未超过天花板的 {level} 不得被改动",
        )

    # Anthropic 原生不吃 effort 字符串，原值要留给 adapter 换算 budget，不参与降档
    body = {}
    gateway._apply_reasoning(body, False, True, "max", api_url="https://api.anthropic.com/v1/messages")
    check(
        body == {"reasoning": {"enabled": True, "effort": "max"}},
        "Anthropic 路径必须保留 max 原值，交给 adapter 换算 budget",
    )

    # ── 主动降档必须留痕，且只在真的降档时留 ────────────────────────────
    def _apply_capturing(*args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gateway._apply_reasoning(*args, **kwargs)
        return buf.getvalue()

    log = _apply_capturing({"model": "deepseek/deepseek-v4-pro"}, True, False, "max", api_url=OR_URL)
    hits = [ln for ln in log.splitlines() if "event=reasoning_effort_downgrade" in ln]
    check(len(hits) == 1, f"发生降档必须恰好记一次，实际 {len(hits)} 次")
    check(
        "provider=openrouter" in hits[0] and "requested=max" in hits[0] and "applied=xhigh" in hits[0],
        f"降档日志字段不完整：{hits[0]}",
    )
    # 日志是给运维看的，不该把请求信息带出去
    check("https://" not in hits[0] and "openrouter.ai" not in hits[0], "降档日志不得包含 URL")
    check("deepseek-v4" not in hits[0] and "deepseek/" not in hits[0], "降档日志不得包含模型名")

    # 没发生降档的路径必须安静：xhigh 是 OR 的天花板本身，原样通过
    quiet = _apply_capturing({}, True, False, "xhigh", api_url=OR_URL)
    check(
        "reasoning_effort_downgrade" not in quiet,
        "xhigh 原样通过 OpenRouter 时不得记降档日志",
    )
    # DeepSeek 直连的 max 也没被动过，同样不许记
    quiet = _apply_capturing({"model": "deepseek-v4-flash"}, False, False, "max", api_url=DEEPSEEK_URL)
    check(
        "reasoning_effort_downgrade" not in quiet,
        "DeepSeek 直连保留 max 时不得记降档日志",
    )
    # off / auto 根本不进降档逻辑
    for skip in ("off", "auto"):
        quiet = _apply_capturing({}, True, False, skip, api_url=OR_URL)
        check(
            "reasoning_effort_downgrade" not in quiet,
            f"{skip} 不涉及降档，不得记日志",
        )

    # Anthropic 的 effort→budget 必须单调递增，否则「超高」会掉回默认值、反而比「高」思考得少。
    # 前提是额度装得下——额度不足时各档被夹到同一个上限是正确行为（见 check_anthropic_budget_clamp），
    # 所以这里显式给足 max_tokens，只验证映射表本身的阶梯。
    budgets = []
    for level in config.REASONING_EFFORT_LEVELS:
        converted = anthropic_adapter.to_anthropic_request(
            {
                "model": "claude-test",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 200000,
                "reasoning": {"enabled": True, "effort": level},
            }
        )
        budgets.append(converted["thinking"]["budget_tokens"])
        check(
            converted["max_tokens"] > converted["thinking"]["budget_tokens"],
            f"budget_tokens 必须小于 max_tokens（{level}）",
        )
    check(
        budgets == sorted(budgets) and len(set(budgets)) == len(budgets),
        f"effort→budget 必须严格递增，实际为 {dict(zip(config.REASONING_EFFORT_LEVELS, budgets))}",
    )


async def check_anthropic_budget_clamp():
    """Anthropic legacy 合同：thinking 只能被 max_tokens 夹小，绝不反向抬高 max_tokens。"""

    def convert(effort, max_tokens=None, enabled=True, reasoning=True):
        payload = {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0.7,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if reasoning:
            payload["reasoning"] = {"enabled": enabled}
            if effort is not None:
                payload["reasoning"]["effort"] = effort
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = anthropic_adapter.to_anthropic_request(payload)
        log = buf.getvalue()
        return (
            out,
            log.count("event=reasoning_effort_budget_clamp"),
            log.count("event=reasoning_effort_disable"),
            log,
        )

    # ① 显式额度：用户要 2000 就必须发 2000，thinking 只能夹到 1999
    out, clamps, disables, log = convert("max", max_tokens=2000)
    check(
        out["max_tokens"] == 2000,
        f"用户显式 max_tokens=2000 必须原样出站，实际 {out['max_tokens']}",
    )
    check(
        out["thinking"]["budget_tokens"] == 1999,
        f"budget 必须夹到 max_tokens-1=1999，实际 {out['thinking']['budget_tokens']}",
    )
    check(clamps == 1, f"发生钳制必须恰好记一次，实际 {clamps} 次")
    check(disables == 0, "发生钳制时不得记 disable 日志")
    line = [ln for ln in log.splitlines() if "budget_clamp" in ln][0]
    for field in ("provider=anthropic", "requested=max", "mapped_budget=64000", "applied_budget=1999", "reason=max_tokens_limit"):
        check(field in line, f"钳制日志缺字段 {field}：{line}")
    check("claude-test" not in line and "http" not in line and "ping" not in line, f"钳制日志不得带模型名/URL/正文：{line}")

    # ② 未传 max_tokens：沿用默认 8192，同样不得被抬高
    out, clamps, disables, _ = convert("max")
    check(out["max_tokens"] == 8192, f"未传 max_tokens 应保持默认 8192，实际 {out['max_tokens']}")
    check(out["thinking"]["budget_tokens"] == 8191, f"budget 应夹到 8191，实际 {out['thinking']['budget_tokens']}")
    check(clamps == 1 and disables == 0, f"默认额度被钳制应恰记一次 clamp，实际 clamp={clamps} disable={disables}")

    # ③ 装得下时保持高档，且必须安静
    out, clamps, disables, _ = convert("max", max_tokens=70000)
    check(out["max_tokens"] == 70000, f"额度充足时 max_tokens 不得改动，实际 {out['max_tokens']}")
    check(out["thinking"]["budget_tokens"] == 64000, f"额度充足时应给满 64000，实际 {out['thinking']['budget_tokens']}")
    check(clamps == 0 and disables == 0, f"未发生钳制不得记日志，实际 clamp={clamps} disable={disables}")

    # ④ 最小边界：<=1024 关闭 thinking，请求照发
    out, clamps, disables, log = convert("max", max_tokens=1024)
    check(out["max_tokens"] == 1024, f"max_tokens=1024 必须原样保留，实际 {out['max_tokens']}")
    check("thinking" not in out, "max_tokens<=1024 时出站不得带 thinking")
    check(out.get("temperature") == 0.7, f"关闭 thinking 时不得强制 temperature=1，实际 {out.get('temperature')}")
    check(disables == 1 and clamps == 0, f"应恰记一次 disable，实际 disable={disables} clamp={clamps}")
    line = [ln for ln in log.splitlines() if "reasoning_effort_disable" in ln][0]
    for field in ("provider=anthropic", "requested=max", "reason=max_tokens_below_minimum"):
        check(field in line, f"关闭日志缺字段 {field}：{line}")

    # ⑤ 相邻边界 1025：仍开思考，夹到 1024
    out, clamps, disables, _ = convert("max", max_tokens=1025)
    check(out["max_tokens"] == 1025, f"max_tokens=1025 必须原样保留，实际 {out['max_tokens']}")
    check(out["thinking"]["budget_tokens"] == 1024, f"budget 应夹到 1024，实际 {out['thinking'].get('budget_tokens')}")
    check(out.get("temperature") == 1, "thinking 生效时仍须 temperature=1")
    check(clamps == 1 and disables == 0, f"1025 应恰记一次 clamp，实际 clamp={clamps} disable={disables}")

    # ⑥ 安静路径：这些情形一律不得出现 clamp/disable 日志
    quiet_cases = [
        ("reasoning 关闭", dict(effort="max", max_tokens=2000, enabled=False)),
        ("不带 reasoning", dict(effort=None, max_tokens=2000, reasoning=False)),
        ("low 且额度充足", dict(effort="low", max_tokens=70000)),
        ("auto 且额度充足", dict(effort=None, max_tokens=70000)),
    ]
    for name, kwargs in quiet_cases:
        _, clamps, disables, _ = convert(**kwargs)
        check(clamps == 0 and disables == 0, f"安静路径「{name}」不得记日志，实际 clamp={clamps} disable={disables}")

    # 非 Anthropic 路径也不得记 Anthropic 的这两种日志
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        gateway._apply_reasoning({}, False, False, "max", api_url="https://api.deepseek.com/v1/chat/completions")
        gateway._apply_reasoning({}, True, False, "max", api_url="https://openrouter.ai/api/v1/chat/completions")
    non_anthropic = buf.getvalue()
    check(
        "budget_clamp" not in non_anthropic and "reasoning_effort_disable" not in non_anthropic,
        "非 Anthropic 路径不得出现 Anthropic 的 clamp/disable 日志",
    )


class _FakeCompressionResponse:
    status_code = 200

    def json(self):
        return {
            "choices": [{
                "message": {"content": "compressed summary"},
                "finish_reason": "stop",
            }]
        }


def _compression_client(captured):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": copy.deepcopy(headers), "body": copy.deepcopy(json)})
            return _FakeCompressionResponse()

    return FakeAsyncClient


async def _run_compression_case(get_float, get_int):
    captured = []

    async def fake_get_config(key):
        values = {
            "handoff_summary_model": "test/model",
            "prompt_compress": "比例={compress_ratio}；上限={compress_output_max}",
        }
        return values.get(key, "")

    async def fake_resolve(_model):
        return "https://upstream.invalid/v1/chat/completions", "test-key", "openai"

    with (
        patch.object(gateway, "get_config", fake_get_config),
        patch.object(gateway, "get_config_float", get_float),
        patch.object(gateway, "get_config_int", get_int),
        patch.object(database, "resolve_model_endpoint", fake_resolve),
        patch.object(gateway.httpx, "AsyncClient", _compression_client(captured)),
    ):
        result = await gateway._compress_for_handoff(
            "old summary",
            [{"role": "user", "content": "new material"}],
        )

    check(result == "compressed summary", "compression response must remain compatible")
    check(len(captured) == 1, "compression must make one background request")
    body = captured[0]["body"]
    system_prompt = body["messages"][0]["content"]
    check("{" not in system_prompt and "}" not in system_prompt, "compression placeholders must not reach the model")
    check(body["max_tokens"] == 2000, "placeholder output max must not rewrite provider token policy")
    return system_prompt


async def check_compression_placeholders():
    async def ratio(*_args, **_kwargs):
        return 0.42

    async def output_max(*_args, **_kwargs):
        return 7777

    configured = await _run_compression_case(ratio, output_max)
    check("比例=42%" in configured, "configured compression ratio must be rendered as a percentage")
    check("上限=7777 token" in configured, "configured compression output max must be rendered")

    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("forced config outage")

    fallback = await _run_compression_case(unavailable, unavailable)
    check("比例=35%" in fallback, "compression ratio must use the safe default on config failure")
    check("上限=4000 token" in fallback, "compression output max must use the safe default on config failure")


async def main():
    failures = []
    for name, case in (
        ("reasoning config", check_reasoning_config_contract),
        ("request reasoning", check_request_reasoning_contract),
        ("anthropic budget clamp", check_anthropic_budget_clamp),
        ("compression placeholders", check_compression_placeholders),
    ):
        try:
            await case()
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"FAIL {failures[-1]}")
    if failures:
        raise AssertionError("; ".join(failures))
    print("PASS: compression placeholders and reasoning effort contracts")


if __name__ == "__main__":
    asyncio.run(main())
