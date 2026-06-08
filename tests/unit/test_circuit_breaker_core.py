from datetime import datetime, timedelta, timezone

from intelligence import circuit_breaker as cb_module
from intelligence.circuit_breaker import CircuitBreaker, get_circuit_breaker


class FixedClockCircuitBreaker(CircuitBreaker):
    def __init__(self, now, *args, **kwargs):
        self.fixed_now = now
        super().__init__(*args, **kwargs)

    def _now_utc(self):
        return self.fixed_now


def _breaker(**config):
    return FixedClockCircuitBreaker(
        datetime(2025, 1, 8, 12, tzinfo=timezone.utc),
        config={"portfolio_balance": 1000.0, **config},
        persist=False,
    )


def test_can_trade_allows_clean_state_and_get_status_reports_limits():
    breaker = _breaker(daily_loss_limit_pct=2.0, weekly_loss_limit_pct=5.0)

    allowed, reason = breaker.can_trade()
    status = breaker.get_status()

    assert allowed is True
    assert reason == "Trading allowed"
    assert status["can_trade"] is True
    assert status["daily_limit_usd"] == 20.0
    assert status["weekly_limit_usd"] == 50.0


def test_daily_and_weekly_loss_limits_block_trading():
    daily = _breaker(daily_loss_limit_pct=1.0)
    daily.state["last_reset_day"] = "2025-01-08"
    daily.state["daily_pnl"] = -10.0

    weekly = _breaker(weekly_loss_limit_pct=2.0)
    weekly.state["last_reset_day"] = "2025-01-08"
    weekly.state["last_reset_week"] = "2025-W01"
    weekly.state["weekly_pnl"] = -20.0

    assert daily.can_trade()[0] is False
    assert "Daily loss limit" in daily.can_trade()[1]
    assert weekly.can_trade()[0] is False
    assert "Weekly loss limit" in weekly.can_trade()[1]


def test_consecutive_losses_trigger_pause_then_time_pause_blocks():
    breaker = _breaker(max_consecutive_losses=2, pause_hours=6)
    breaker.state["last_reset_day"] = "2025-01-08"
    breaker.state["last_reset_week"] = "2025-W01"
    breaker.state["consecutive_losses"] = 2

    allowed, reason = breaker.can_trade()
    paused_allowed, paused_reason = breaker.can_trade()

    assert allowed is False
    assert "pausing" in reason
    assert breaker.state["consecutive_losses"] == 0
    assert paused_allowed is False
    assert "Paused" in paused_reason


def test_expired_or_invalid_pause_is_cleared():
    now = datetime(2025, 1, 8, 12, tzinfo=timezone.utc)
    expired = FixedClockCircuitBreaker(now, persist=False)
    expired.state["stopped_until"] = (now - timedelta(hours=1)).isoformat()

    invalid = FixedClockCircuitBreaker(now, persist=False)
    invalid.state["stopped_until"] = "not-a-date"

    assert expired.can_trade() == (True, "Trading allowed")
    assert expired.state["stopped_until"] is None
    assert invalid.can_trade() == (True, "Trading allowed")
    assert invalid.state["stopped_until"] is None


def test_record_trade_updates_loss_streak_and_emergency_stop():
    breaker = _breaker(emergency_stop_pct=10.0)

    breaker.record_trade_result(-50.0, is_win=False)
    assert breaker.state["daily_pnl"] == -50.0
    assert breaker.state["weekly_pnl"] == -50.0
    assert breaker.state["consecutive_losses"] == 1

    breaker.record_trade_result(20.0, is_win=True)
    assert breaker.state["consecutive_losses"] == 0

    breaker.record_trade_result(-200.0, is_win=False)
    assert breaker.state["permanent_stop"] is True
    assert breaker.can_trade()[0] is False
    assert "PERMANENT STOP" in breaker.can_trade()[1]


def test_reset_and_period_rollover_refresh_state():
    breaker = _breaker()
    breaker.state.update(
        {
            "daily_pnl": -12.0,
            "weekly_pnl": -20.0,
            "consecutive_losses": 3,
            "last_reset_day": "2025-01-07",
            "last_reset_week": "2025-W00",
        }
    )

    breaker._reset_if_new_period()
    assert breaker.state["daily_pnl"] == 0.0
    assert breaker.state["weekly_pnl"] == 0.0
    assert breaker.state["consecutive_losses"] == 0

    breaker.state["permanent_stop"] = True
    breaker.reset()
    assert breaker.state["permanent_stop"] is False
    assert breaker.state["last_reset_day"] == "2025-01-08"


def test_persistence_and_singleton_paths(tmp_path, monkeypatch):
    state_file = tmp_path / "cb_state.json"
    monkeypatch.setattr(cb_module, "_STATE_FILE", state_file)
    monkeypatch.setattr(cb_module, "_cb_instance", None)

    persisted = CircuitBreaker(persist=True)
    persisted.record_trade_result(-7.0, is_win=False)

    loaded = CircuitBreaker(persist=True)
    assert loaded.state["daily_pnl"] == -7.0
    assert loaded.state["consecutive_losses"] == 1

    first = get_circuit_breaker({"portfolio_balance": 1234.0})
    second = get_circuit_breaker({"portfolio_balance": 1.0})
    assert first is second
    assert second.config["portfolio_balance"] == 1234.0
