import io
import json
import sqlite3
import sys
import types

from intelligence.ml import risk_manager as rm


def test_get_correlation_group_and_drawdown_breaker_empty(monkeypatch):
    assert "BTCUSD" in rm.get_correlation_group("btcusd")
    assert rm.get_correlation_group("UNKNOWN") is None

    monkeypatch.setattr(rm, "_get_recent_outcomes", lambda symbol=None, limit=20: [])
    result = rm.check_drawdown_circuit_breaker("BTCUSD")
    assert result["ok"] is True
    assert result["consecutive_losses"] == 0


def test_get_recent_outcomes_and_circuit_breaker_from_db(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                outcome TEXT,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO paper_trades (symbol, outcome, status, opened_at, closed_at)
            VALUES (?, ?, 'CLOSED', '2026-01-01', ?)
            """,
            [
                ("BTCUSD", "LOSS", "2026-01-05"),
                ("BTCUSD", "LOSS", "2026-01-04"),
                ("BTCUSD", "WIN", "2026-01-03"),
                ("ETHUSD", "LOSS", "2026-01-02"),
            ],
        )
    monkeypatch.setattr(rm, "PAPER_DB", str(db_path))
    monkeypatch.setattr(rm, "CIRCUIT_BREAKER_CONSECUTIVE_LOSSES", 2)

    assert rm._get_recent_outcomes("BTCUSD", limit=5)[:2] == ["LOSS", "LOSS"]
    assert rm._get_recent_outcomes(limit=2) == ["LOSS", "LOSS"]
    blocked = rm.check_drawdown_circuit_breaker("BTCUSD")
    assert blocked["blocked"] is True
    assert blocked["threshold"] == 2


def test_kelly_position_size_and_history_based_variant(monkeypatch, tmp_path):
    base = rm.kelly_position_size(0.6, 2.0, 1.0, balance=1000.0)
    assert base["positive_edge"] is True
    assert base["recommended_risk_usd"] > 0

    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                outcome TEXT,
                pnl_usd REAL,
                entry_price REAL,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        rows = [("BTCUSD", "WIN", 20.0, 100.0, "CLOSED", "2026-01-01", "2026-01-01")] * 6
        rows += [("BTCUSD", "LOSS", -10.0, 100.0, "CLOSED", "2026-01-01", "2026-01-01")] * 4
        con.executemany("INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    monkeypatch.setattr(rm, "PAPER_DB", str(db_path))

    history = rm.kelly_from_paper_trades("BTCUSD", limit=20)
    assert history["available"] is True
    assert history["n_trades"] == 10
    assert history["symbol"] == "BTCUSD"
    history_all = rm.kelly_from_paper_trades(limit=20)
    assert history_all["available"] is True
    assert history_all["symbol"] == "ALL"


def test_kelly_history_handles_errors_and_insufficient_data(monkeypatch):
    monkeypatch.setattr(rm.sqlite3, "connect", lambda path: (_ for _ in ()).throw(sqlite3.OperationalError("db down")))
    assert rm.kelly_from_paper_trades("BTCUSD") == {"available": False}


def test_kelly_history_handles_insufficient_and_one_sided_samples(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                symbol TEXT,
                outcome TEXT,
                pnl_usd REAL,
                entry_price REAL,
                status TEXT,
                opened_at TEXT,
                closed_at TEXT
            )
            """
        )
        few_rows = [("ETHUSD", "WIN", 10.0, 100.0, "CLOSED", "2026-01-01", "2026-01-01")] * 3
        con.executemany("INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?)", few_rows)

    monkeypatch.setattr(rm, "PAPER_DB", str(db_path))
    assert rm.kelly_from_paper_trades("ETHUSD", limit=20) == {
        "available": False,
        "reason": "insufficient trades (3)",
    }

    with sqlite3.connect(db_path) as con:
        con.execute("DELETE FROM paper_trades")
        one_sided_rows = [("ETHUSD", "WIN", 10.0, 100.0, "CLOSED", "2026-01-01", "2026-01-01")] * 10
        con.executemany("INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?)", one_sided_rows)

    assert rm.kelly_from_paper_trades("ETHUSD", limit=20) == {
        "available": False,
        "reason": "no wins or losses to compute edge",
    }


def test_volatility_adjusted_size_and_funding_gate_cache(monkeypatch):
    sized = rm.volatility_adjusted_size(1.0, atr_pct=3.0, vix=40.0)
    assert sized["adjusted_risk_pct"] < 1.0
    assert sized["vix_scalar"] <= 0.5
    assert rm.volatility_adjusted_size(1.0, atr_pct=0.001, vix=0.0)["vix_scalar"] == 1.0

    monkeypatch.setattr(rm, "_FUNDING_CACHE", {"BTCUSDT": {"rate": 0.002, "ts": 10_000}})

    fake_time = types.SimpleNamespace(time=lambda: 10_100)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    cached_rate = rm.get_funding_rate("BTCUSD")
    assert cached_rate == 0.002


def test_get_funding_rate_fetches_remote_and_handles_failure(monkeypatch):
    monkeypatch.setattr(rm, "_FUNDING_CACHE", {})

    fake_time_mod = types.SimpleNamespace(time=lambda: 1000.0)
    monkeypatch.setitem(sys.modules, "time", fake_time_mod)

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"lastFundingRate": "0.0015"}).encode("utf-8")

    fake_urllib_request = types.SimpleNamespace(urlopen=lambda url, timeout=5: FakeResp())
    fake_urllib = types.SimpleNamespace(request=fake_urllib_request)
    monkeypatch.setitem(sys.modules, "urllib.request", fake_urllib_request)
    monkeypatch.setitem(sys.modules, "urllib", fake_urllib)

    rate = rm.get_funding_rate("ETHUSD")
    assert rate == 0.0015
    assert rm.check_funding_rate_gate("ETHUSD", "BUY")["blocked"] is True
    assert rm.check_funding_rate_gate("ETHUSD", "SELL")["blocked"] is False
    monkeypatch.setattr(rm, "get_funding_rate", lambda symbol: -0.0015)
    sell_gate = rm.check_funding_rate_gate("ETHUSD", "SELL")
    assert sell_gate["blocked"] is True
    assert "avoid SELL" in sell_gate["reason"]

    monkeypatch.setattr(rm, "get_funding_rate", lambda symbol: None)
    assert rm.check_funding_rate_gate("ETHUSD", "BUY")["checked"] is False


def test_full_risk_check_combines_blockers(monkeypatch):
    monkeypatch.setattr(rm, "check_drawdown_circuit_breaker", lambda symbol=None: {"blocked": True, "reason": "too many losses"})
    monkeypatch.setattr(rm, "check_funding_rate_gate", lambda symbol, side: {"blocked": True, "reason": "crowded", "ok": False, "checked": True})
    monkeypatch.setattr(rm, "kelly_from_paper_trades", lambda symbol=None: {"available": True, "positive_edge": True, "recommended_risk_pct": 2.0})
    monkeypatch.setattr(rm, "volatility_adjusted_size", lambda base_risk_pct, atr_pct, vix=0.0: {"adjusted_risk_pct": 0.05})

    result = rm.full_risk_check(
        symbol="ETHUSD",
        side="BUY",
        atr_pct=2.0,
        vix=30.0,
        open_symbols=["BTCUSD"],
        asset_class="CRYPTO",
    )

    assert result["ok"] is False
    assert "correlation" in result["blocked_by"]
    assert "drawdown_circuit_breaker" in result["blocked_by"]
    assert "funding_rate" in result["blocked_by"]
    assert result["correlation_conflict"] == ["BTCUSD"]
    assert any("Position too small" in warning for warning in result["warnings"])


def test_full_risk_check_safe_path_without_crypto(monkeypatch):
    monkeypatch.setattr(rm, "check_drawdown_circuit_breaker", lambda symbol=None: {"blocked": False, "reason": ""})
    monkeypatch.setattr(rm, "kelly_from_paper_trades", lambda symbol=None: {"available": False})
    monkeypatch.setattr(rm, "volatility_adjusted_size", lambda base_risk_pct, atr_pct, vix=0.0: {"adjusted_risk_pct": 1.25})

    result = rm.full_risk_check(
        symbol="GOLD",
        side="SELL",
        atr_pct=1.0,
        vix=10.0,
        open_symbols=[],
        asset_class="MACRO",
    )

    assert result["ok"] is True
    assert result["funding"]["checked"] is False
    assert result["sizing"]["final_risk_pct"] == 1.25


def test_full_risk_check_handles_non_conflicting_crypto_path(monkeypatch):
    monkeypatch.setattr(rm, "check_drawdown_circuit_breaker", lambda symbol=None: {"blocked": False, "reason": ""})
    monkeypatch.setattr(rm, "check_funding_rate_gate", lambda symbol, side: {"blocked": False, "reason": "", "ok": True, "checked": True})
    monkeypatch.setattr(rm, "kelly_from_paper_trades", lambda symbol=None: {"available": True, "positive_edge": False, "recommended_risk_pct": 2.5})
    monkeypatch.setattr(rm, "volatility_adjusted_size", lambda base_risk_pct, atr_pct, vix=0.0: {"adjusted_risk_pct": 0.5})

    result = rm.full_risk_check(
        symbol="EURUSD",
        side="BUY",
        atr_pct=1.2,
        vix=18.0,
        open_symbols=["USDJPY"],
        asset_class="CRYPTO",
    )

    assert result["ok"] is True
    assert result["blocked_by"] == []
    assert "correlation_conflict" not in result
    assert result["funding"]["checked"] is True
    assert result["sizing"]["final_risk_pct"] == 0.5


def test_full_risk_check_with_open_symbols_but_no_group(monkeypatch):
    monkeypatch.setattr(rm, "check_drawdown_circuit_breaker", lambda symbol=None: {"blocked": False, "reason": ""})
    monkeypatch.setattr(rm, "check_funding_rate_gate", lambda symbol, side: {"blocked": False, "reason": "", "ok": True, "checked": True})
    monkeypatch.setattr(rm, "kelly_from_paper_trades", lambda symbol=None: {"available": True, "positive_edge": True, "recommended_risk_pct": 1.5})
    monkeypatch.setattr(rm, "volatility_adjusted_size", lambda base_risk_pct, atr_pct, vix=0.0: {"adjusted_risk_pct": 0.75})

    result = rm.full_risk_check(
        symbol="UNKNOWN",
        side="SELL",
        open_symbols=["BTCUSD"],
        asset_class="CRYPTO",
    )

    assert result["ok"] is True
    assert result["blocked_by"] == []
    assert "correlation_conflict" not in result
