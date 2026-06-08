from intelligence.ml import signal_model


def test_paper_label_quality_decision_respects_symbol_policy(monkeypatch):
    row = {
        "entry_source": "auto_paper",
        "symbol": "ETHUSD",
        "side": "SELL",
        "pnl_usd": -1.0,
        "close_reason": "stop_loss",
    }
    features = {f"f{i}": 1.0 for i in range(20)}

    import intelligence.ml.performance_feedback as performance_feedback
    import intelligence.ml.symbol_policy as symbol_policy

    monkeypatch.setattr(performance_feedback, "paper_training_label_gate", lambda *args, **kwargs: {"ok": True, "blockers": []})
    monkeypatch.setattr(symbol_policy, "get_symbol_policy", lambda *args, **kwargs: {"action": "block", "symbol": "ETHUSD", "side": "SELL"})

    decision = signal_model._paper_label_quality_decision(row, features)

    assert decision["include"] is False
    assert "policy_blocked" in decision["reasons"]
