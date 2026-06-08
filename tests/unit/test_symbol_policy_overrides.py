from intelligence.ml import symbol_policy


def test_symbol_policy_override_round_trip(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))
    symbol_policy._policy_cache["loaded_at"] = 0.0
    symbol_policy._policy_cache["payload"] = None

    reduced = symbol_policy.upsert_symbol_policy_override("ETHUSD", "buy", "reduce", size_multiplier=0.4, note="trim risk")
    listed = symbol_policy.list_symbol_policy_overrides()
    cleared = symbol_policy.upsert_symbol_policy_override("ETHUSD", "BUY", "allow")

    assert reduced["action"] == "reduce"
    assert reduced["size_multiplier"] == 0.4
    assert listed[0]["symbol"] == "ETHUSD"
    assert cleared["action"] == "allow"


def test_symbol_policy_getters_cover_db_fallbacks_and_validation(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    original_snapshot = symbol_policy.get_symbol_policy_snapshot
    monkeypatch.setattr(symbol_policy, "_POLICY_DB", str(db_path))
    symbol_policy._policy_cache["loaded_at"] = 0.0
    symbol_policy._policy_cache["payload"] = None
    monkeypatch.setattr(symbol_policy, "get_symbol_policy_snapshot", lambda force_refresh=False: {"rows": []})

    blocked = symbol_policy.upsert_symbol_policy_override("ethusdt", "sell", "block", note="hard stop")
    reduced = symbol_policy.upsert_symbol_policy_override("btcusd", "buy", "reduce", size_multiplier=5.0, note="trim")

    assert blocked["symbol"] == "ETH"
    assert blocked["action"] == "block"
    assert blocked["note"] == "hard stop"
    assert reduced["symbol"] == "BTCUSD"
    assert reduced["action"] == "reduce"
    assert reduced["size_multiplier"] == 1.0

    listed = symbol_policy.list_symbol_policy_overrides()
    assert len(listed) == 2

    default_policy = symbol_policy.get_symbol_policy("solusd", "buy", force_refresh=True)
    assert default_policy["action"] == "allow"
    assert default_policy["symbol"] == "SOLUSD"

    try:
        symbol_policy.upsert_symbol_policy_override("ETHUSD", "BUY", "pause")
    except ValueError as exc:
        assert "action must be block, reduce, or allow" in str(exc)
    else:
        raise AssertionError("expected invalid action to raise ValueError")

    monkeypatch.setattr(symbol_policy, "get_symbol_policy_snapshot", original_snapshot)
    monkeypatch.setattr(symbol_policy, "get_feedback_snapshot", lambda force_refresh=False: {"symbol_side": {}})
    refreshed = symbol_policy.refresh_symbol_policy_cache()
    assert refreshed["available"] is True
