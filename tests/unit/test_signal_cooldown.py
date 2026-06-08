from intelligence.ml import signal_cooldown


def test_check_returns_not_cooling_when_registry_empty():
    signal_cooldown.clear()

    result = signal_cooldown.check("btcusd", "1h", "buy", 100.0)

    assert result == {"cooling_down": False, "reason": ""}


def test_register_then_check_blocks_same_zone_within_cooldown(monkeypatch):
    signal_cooldown.clear()
    current_time = 1_000_000.0
    monkeypatch.setattr(signal_cooldown.time, "time", lambda: current_time)

    signal_cooldown.register("btcusd", "1h", "buy", 100.0)

    monkeypatch.setattr(signal_cooldown.time, "time", lambda: current_time + 30 * 60)
    result = signal_cooldown.check("BTCUSD", "1h", "BUY", 100.2)

    assert result["cooling_down"] is True
    assert result["remaining_minutes"] == 450
    assert "same zone (100.00)" in result["reason"]


def test_check_allows_reentry_when_zone_moved_far_enough(monkeypatch):
    signal_cooldown.clear()
    base_time = 2_000_000.0
    monkeypatch.setattr(signal_cooldown.time, "time", lambda: base_time)
    signal_cooldown.register("ETHUSD", "15m", "sell", 100.0)

    monkeypatch.setattr(signal_cooldown.time, "time", lambda: base_time + 5 * 60)
    result = signal_cooldown.check("ETHUSD", "15m", "SELL", 101.0)

    assert result == {"cooling_down": False, "reason": ""}


def test_check_allows_reentry_after_cooldown_expires(monkeypatch):
    signal_cooldown.clear()
    base_time = 3_000_000.0
    monkeypatch.setattr(signal_cooldown.time, "time", lambda: base_time)
    signal_cooldown.register("XAUUSD", "4h", "buy", 2500.0)

    monkeypatch.setattr(signal_cooldown.time, "time", lambda: base_time + (25 * 3600))
    result = signal_cooldown.check("XAUUSD", "4h", "BUY", 2500.1)

    assert result == {"cooling_down": False, "reason": ""}


def test_clear_symbol_only_removes_matching_symbol(monkeypatch):
    signal_cooldown.clear()
    monkeypatch.setattr(signal_cooldown.time, "time", lambda: 4_000_000.0)
    signal_cooldown.register("BTCUSD", "1h", "buy", 100.0)
    signal_cooldown.register("ETHUSD", "1h", "buy", 200.0)

    signal_cooldown.clear("BTCUSD")

    assert signal_cooldown.check("BTCUSD", "1h", "BUY", 100.0) == {"cooling_down": False, "reason": ""}
    assert signal_cooldown.check("ETHUSD", "1h", "BUY", 200.0)["cooling_down"] is True
