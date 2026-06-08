import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from intelligence import compaction
from intelligence.agents.pattern_agent import create_pattern_agent
from intelligence.agents.trend_agent import create_trend_agent
from intelligence.tools.calendar_tools import CalendarTools


def test_compaction_estimates_tokens_and_truncates_old_tool_results():
    history = [
        {"role": "user", "content": "hello"},
        {"role": "tool", "content": "a" * 250},
        {"role": "assistant", "content": "ok"},
        {"role": "tool", "content": "b" * 250},
        {"role": "tool", "content": "c" * 250},
    ]

    compacted = compaction.microcompact_history(history, keep_recent=1)

    assert compaction.estimate_tokens("abcd" * 3) == 3
    assert compacted[1]["content"] == "[Content truncated for background efficiency]"
    assert compacted[3]["content"] == "[Content truncated for background efficiency]"
    assert compacted[4]["content"] == "c" * 250
    assert history[1]["content"] == "a" * 250


def test_compaction_summary_prompt_keeps_short_messages_only():
    prompt = compaction.get_compaction_summary_prompt(
        [
            {"role": "user", "content": "BTC plan risk 1%"},
            {"role": "tool", "content": "x" * 1200},
            {"role": "assistant", "content": "Pending: monitor CPI"},
        ]
    )

    assert "Compact Memory" in prompt
    assert "BTC plan risk 1%" in prompt
    assert "Pending: monitor CPI" in prompt
    assert "x" * 100 not in prompt


def test_calendar_tools_fetches_caches_filters_and_handles_errors(monkeypatch):
    xml = """
    <weeklyevents>
      <event>
        <title>CPI</title><country>USD</country><date>01-08-2025</date><time>8:30am</time>
        <impact>High</impact><forecast>3.0%</forecast><previous>3.1%</previous>
      </event>
      <event>
        <title>Low event</title><country>EUR</country><date>01-08-2025</date><impact>Low</impact>
      </event>
    </weeklyevents>
    """
    calls = {"count": 0}

    def fake_get(*_args, **_kwargs):
        calls["count"] += 1
        return SimpleNamespace(status_code=200, text=xml)

    monkeypatch.setattr("intelligence.tools.calendar_tools.requests.get", fake_get)
    monkeypatch.setattr(
        "intelligence.tools.calendar_tools.datetime",
        SimpleNamespace(
            now=lambda *args, **kwargs: datetime(2025, 1, 8, tzinfo=timezone.utc)
            if args or kwargs
            else datetime(2025, 1, 8),
        ),
    )
    tools = CalendarTools()

    first = tools.fetch_calendar()
    second = tools.fetch_calendar()
    high = tools.get_upcoming_high_impact(["USD", "EUR"])

    assert calls["count"] == 1
    assert first is second
    assert first[0]["title"] == "CPI"
    assert high == [first[0]]

    stale = CalendarTools()
    monkeypatch.setattr(
        "intelligence.tools.calendar_tools.requests.get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=500, text=""),
    )
    assert stale.fetch_calendar() == []

    monkeypatch.setattr(
        "intelligence.tools.calendar_tools.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert CalendarTools().fetch_calendar() == []


class FakeModels:
    def __init__(self, payload=None, raises=None):
        self.payload = payload or {}
        self.raises = raises
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return SimpleNamespace(text=json.dumps(self.payload))


def test_trend_agent_handles_missing_chart_success_and_errors():
    ok_models = FakeModels(
        {
            "channel_type": "ASCENDING",
            "trend_direction": "UPTREND",
            "price_position": "NEAR_SUPPORT",
            "channel_slope": "GRADUAL",
            "trend_strength": "STRONG",
            "trend_bias": "BULLISH",
            "confidence": 77,
            "support_level": "100",
            "resistance_level": "120",
            "summary": "Ascending support is holding.",
        }
    )
    node = create_trend_agent(SimpleNamespace(models=ok_models))

    missing = node({})
    success = node(
        {
            "symbol": "ETH",
            "timeframe": "1h",
            "trend_chart_b64": base64.b64encode(b"png").decode(),
            "indicator_summary": {"adx": {"value": 28, "signal": "Strong"}},
        }
    )
    failure = create_trend_agent(SimpleNamespace(models=FakeModels(raises=RuntimeError("llm down"))))(
        {"trend_chart_b64": base64.b64encode(b"png").decode()}
    )

    assert missing["trend_direction"] == "UNKNOWN"
    assert success["trend_direction"] == "UPTREND"
    assert success["trend_bias"] == "BULLISH"
    assert success["trend_confidence"] == 77
    assert ok_models.calls
    assert failure["trend_confidence"] == 0


def test_pattern_agent_text_fallback_scores_ict_and_classic_patterns():
    node = create_pattern_agent(SimpleNamespace(models=FakeModels()))

    bullish = node(
        {
            "symbol": "BTC",
            "indicator_summary": {
                "patterns": {"detected": ["Bullish Engulfing"], "observation": "strong close"},
                "trend_analysis": {
                    "primary_trend": "UP",
                    "market_phase": "TREND",
                    "levels": {"support": 100, "resistance": 120},
                },
                "smart_money": {
                    "structure": {"choch": True, "structure": "BULLISH", "last_bos": "BULLISH_BOS"},
                    "nearest_ob": {"type": "bullish", "top": 110, "bottom": 100},
                    "nearest_fvg": {"type": "bullish"},
                    "sweeps": {"sweep_detected": True, "type": "bullish"},
                },
            },
        }
    )
    bearish = node(
        {
            "indicator_summary": {
                "patterns": {"detected": ["Head & Shoulders"]},
                "trend_analysis": {"primary_trend": "DOWN"},
                "smart_money": {
                    "structure": {"choch": True, "structure": "BEARISH", "last_bos": "BEARISH_BOS"},
                    "nearest_ob": {"type": "bearish", "top": 110, "bottom": 100},
                    "nearest_fvg": {"type": "bearish"},
                    "sweeps": {"sweep_detected": True, "type": "bearish"},
                },
            }
        }
    )
    neutral = node({"indicator_summary": {"patterns": {"detected": ["None"]}, "trend_analysis": {}}})

    assert bullish["pattern_bias"] == "BULLISH"
    assert bullish["pattern_confidence"] == 82
    assert "CHoCH" in bullish["detected_pattern"]
    assert bearish["pattern_bias"] == "BEARISH"
    assert neutral["pattern_bias"] == "NEUTRAL"


def test_pattern_agent_vision_success_and_error_paths():
    models = FakeModels(
        {
            "pattern_name": "Bullish Flag",
            "pattern_type": "BULLISH",
            "completion_status": "COMPLETE",
            "breakout_direction": "UP",
            "confidence": 81,
            "key_levels": {"support": "100", "resistance": "120", "breakout_target": "130"},
            "summary": "Momentum continuation pattern.",
        }
    )
    node = create_pattern_agent(SimpleNamespace(models=models))

    success = node({"kline_chart_b64": base64.b64encode(b"png").decode()})
    failure = create_pattern_agent(SimpleNamespace(models=FakeModels(raises=RuntimeError("bad image"))))(
        {"kline_chart_b64": base64.b64encode(b"png").decode()}
    )

    assert success["detected_pattern"] == "Bullish Flag"
    assert success["pattern_bias"] == "BULLISH"
    assert success["pattern_confidence"] == 81
    assert models.calls
    assert failure["detected_pattern"] == "UNKNOWN"
