import json
from types import SimpleNamespace

from intelligence.agents import master_agent


class FakeModels:
    def __init__(self, payload=None, raises=None):
        self.payload = payload or {}
        self.raises = raises
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(text=text)


def _base_state():
    return {
        "symbol": "BTC",
        "timeframe": "15m",
        "asset_class": "CRYPTO",
        "trade_decision": "LONG",
        "decision_confidence": 82,
        "indicator_report": "Bullish structure",
        "pattern_report": "Pattern aligns",
        "trend_report": "Trend aligns",
        "indicator_bias": "BULLISH",
        "pattern_bias": "BULLISH",
        "trend_bias": "BULLISH",
        "sentiment_score": 20,
        "sentiment_label": "BULLISH",
        "sentiment_report": "Supportive news flow",
        "risk_reward_ratio": 2.2,
        "quality_gate_mode": "observe_only",
        "quality_gate": {"live_ready": False},
        "entry_zone": {"low": 100, "high": 102, "note": "OB retest"},
        "stop_loss": {"price": 96, "invalidation": "below swing low"},
        "take_profit": {"tp1": 108, "tp2": 114},
        "ml_signal": {
            "available": True,
            "buy_prob": 0.8,
            "buy_pct": 80,
            "sell_pct": 20,
            "neural_alignment": True,
            "mtf_blocked": False,
        },
        "intermarket": {
            "macro_bias": "RISK_ON",
            "dxy": {"trend": "DOWN", "value": 101.2},
            "vix": {"level": "LOW", "value": 13.5},
            "fear_greed": {"value": 68, "label": "Greed"},
            "btc_dominance": {"value": 54.3},
            "funding": {"rate_pct": 0.01, "bias": "NEUTRAL"},
            "liquidation": {"liq_bias": "BULLISH", "buy_liq": 4, "sell_liq": 12},
            "oi_trend": {"oi_trend": "RISING", "oi_change_pct": 2.1},
            "forex_context": "",
            "metals_context": "",
        },
        "indicator_summary": {
            "price": 101,
            "hurst": {"h100": 0.62, "regime": "TRENDING"},
            "higher_timeframe": {"bias": "BULLISH", "adx": 28, "timeframe": "1h"},
            "macd_histogram": {"value": 0.5},
            "vwap": {"position": "ABOVE"},
            "rsi": {"value": 55},
            "ema": {"signal": "BULLISH"},
            "smart_money": {
                "regime": "TREND",
                "session": "NEW_YORK",
                "structure": {"structure": "BULLISH", "last_bos": "BULLISH_BOS", "choch": True},
                "nearest_ob": {"type": "BULLISH_OB", "top": 102, "bottom": 99, "strength": "HIGH"},
                "nearest_fvg": {"type": "BULLISH_FVG", "top": 103, "bottom": 100},
                "liquidity": {"buy_side": [108, 110], "sell_side": [96], "nearest_sweep_target": 108},
                "sweeps": {"sweep_detected": True, "type": "SELL_SIDE", "level": 97},
            },
        },
        "directional_correlation": {"confirmed": True, "score": 0.9, "conflicts": []},
    }


def _install_mocks(monkeypatch, *, cooldown=None, protection=None, news=None, drift=None, threshold=0.62):
    cooldown_calls = []

    monkeypatch.setattr(master_agent, "get_reflexive_context", lambda *_args, **_kwargs: {
        "lessons": "Wait for clean alignment.",
        "bias_adjustments": {"tech_weight": 1.0, "sent_weight": 1.0, "conf_weight": 1.0, "risk_scale": 1.0},
    })
    monkeypatch.setattr(master_agent, "format_symbol_memory", lambda *_args, **_kwargs: "Recent BTC trades")
    monkeypatch.setattr(master_agent, "_get_market_regime", lambda: "RISK_ON")
    monkeypatch.setattr(master_agent, "get_threshold_for_side", lambda *_args, **_kwargs: threshold)
    monkeypatch.setattr(master_agent, "score_signal_feedback", lambda *_args, **_kwargs: {
        "probability_adjustment": 0.0,
        "notes": ["stable"],
    })
    monkeypatch.setattr(master_agent, "drift_shield", SimpleNamespace(
        check_drift=lambda _indicators: drift or {"integrity_score": 88, "status": "STABLE", "warnings": []}
    ))
    monkeypatch.setattr(master_agent, "risk_manager", SimpleNamespace(
        check_correlation_risk=lambda _symbol: {"status": "OK", "max_corr": 0.31},
        check_equity_protection=lambda: protection or {"status": "OK", "current_dd": 1.5, "reason": ""},
        check_news_shield=lambda _symbol: news or {"status": "OK", "reason": ""},
        calculate_kelly_size=lambda **_kwargs: 0.12,
    ))
    monkeypatch.setattr(master_agent, "cooldown_check", lambda symbol, timeframe, decision, zone_mid: (
        cooldown_calls.append((symbol, timeframe, decision, zone_mid)) or
        (cooldown or {"cooling_down": False, "reason": ""})
    ))
    monkeypatch.setattr(master_agent, "cooldown_register", lambda symbol, timeframe, decision, zone_mid: (
        cooldown_calls.append(("register", symbol, timeframe, decision, zone_mid))
    ))
    return cooldown_calls


def test_master_agent_helpers_cover_conflict_and_confluence():
    conflict = master_agent._compute_agent_conflict(
        {"indicator_bias": "BULLISH", "pattern_bias": "BEARISH", "trend_bias": "NEUTRAL"}
    )
    assert conflict == {"has_conflict": True, "bull_votes": 1, "bear_votes": 1}

    majority = master_agent._compute_agent_conflict(
        {"indicator_bias": "BULLISH", "pattern_bias": "BULLISH", "trend_bias": "BEARISH"}
    )
    assert majority["has_conflict"] is False

    hold_score, hold_breakdown = master_agent._compute_confluence_score({"trade_decision": "HOLD"})
    assert hold_score == 30.0
    assert hold_breakdown == "HOLD"

    score, breakdown = master_agent._compute_confluence_score(_base_state())
    assert score >= 85
    assert "votes=3/3" in breakdown
    assert "rr=2.2(+7)" in breakdown


def test_master_agent_success_path_observe_only_zeroes_live_size(monkeypatch):
    cooldown_calls = _install_mocks(monkeypatch)
    client = SimpleNamespace(models=FakeModels({
        "decision": "LONG",
        "confidence": 78,
        "reasoning": "HTF, OB, session and flow align.",
        "counter_evidence": "Funding could get crowded.",
        "risk_factors": ["event risk"],
        "entry_type": "LIMIT",
    }))

    result = master_agent.create_master_agent(client)(_base_state())

    assert result["master_decision"] == "LONG"
    assert result["signal_grade"] in {"A", "A+"}
    assert result["size_multiplier"] == 0.0
    assert result["kelly_size"] == 0.0
    assert result["portfolio_health"] == "OK"
    assert "MASTER DECISION" in result["master_report"]
    assert "observe_only" in result["master_report"]
    assert any(call[0] == "register" for call in cooldown_calls)
    assert client.models.calls[0]["config"]["response_mime_type"] == "application/json"


def test_master_agent_blocks_on_sentiment_contradiction(monkeypatch):
    _install_mocks(monkeypatch)
    state = _base_state()
    state["sentiment_score"] = -90
    client = SimpleNamespace(models=FakeModels({
        "decision": "LONG",
        "confidence": 76,
        "reasoning": "LLM liked the setup.",
        "counter_evidence": "Sentiment is weak.",
        "risk_factors": [],
        "entry_type": "MARKET",
    }))

    result = master_agent.create_master_agent(client)(state)

    assert result["master_decision"] == "NO_TRADE"
    assert "Sentiment strongly BEARISH" in result["master_reasoning"]


def test_master_agent_blocks_on_zone_cooldown(monkeypatch):
    cooldown_calls = _install_mocks(
        monkeypatch,
        cooldown={"cooling_down": True, "reason": "same zone traded 10m ago"},
    )
    client = SimpleNamespace(models=FakeModels({
        "decision": "LONG",
        "confidence": 79,
        "reasoning": "Setup is clean.",
        "counter_evidence": "Could fail at resistance.",
        "risk_factors": [],
        "entry_type": "LIMIT",
    }))

    result = master_agent.create_master_agent(client)(_base_state())

    assert result["master_decision"] == "NO_TRADE"
    assert "ZONE COOLDOWN: same zone traded 10m ago" in result["filter_notes"]
    assert any(call[0] == "BTC" for call in cooldown_calls if isinstance(call, tuple))
    assert not any(call[0] == "register" for call in cooldown_calls)


def test_master_agent_handles_llm_error(monkeypatch):
    _install_mocks(monkeypatch)
    client = SimpleNamespace(models=FakeModels(raises=RuntimeError("llm down")))

    result = master_agent.create_master_agent(client)(_base_state())

    assert result["master_decision"] == "NO_TRADE"
    assert result["master_confidence"] == 0.0
    assert "Master agent error" in result["master_reasoning"]
