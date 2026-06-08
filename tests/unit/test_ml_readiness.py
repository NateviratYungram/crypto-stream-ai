import sqlite3
from contextlib import closing

from intelligence.ml import readiness


def test_paper_trade_performance_computes_profit_factor(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            """
            CREATE TABLE paper_trades (
                id TEXT, symbol TEXT, outcome TEXT, pnl_usd REAL,
                status TEXT, opened_at TEXT, closed_at TEXT
            )
            """
        )
        con.executemany(
            """
            INSERT INTO paper_trades
            (id, symbol, outcome, pnl_usd, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, 'CLOSED', ?, ?)
            """,
            [
                ("1", "EURUSD", "WIN", 30.0, "2026-01-01", "2026-01-01"),
                ("2", "EURUSD", "LOSS", -10.0, "2026-01-02", "2026-01-02"),
                ("3", "GOLD", "WIN", 20.0, "2026-01-03", "2026-01-03"),
            ],
        )
        con.commit()

    monkeypatch.setenv("PAPER_TRADE_DB", str(db_path))

    result = readiness.get_paper_trade_performance()

    assert result["total"] == 3
    assert result["wins"] == 2
    assert result["losses"] == 1
    assert result["win_rate"] == 0.6667
    assert result["profit_factor"] == 5.0
    assert result["expectancy_usd"] == 13.3333


def test_live_execution_gate_blocks_when_readiness_fails(monkeypatch):
    monkeypatch.delenv("ALLOW_UNREADY_LIVE_TRADING", raising=False)
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda **_: {"passed": False, "blockers": [{"name": "paper_label_count"}]},
    )

    passed, report = readiness.live_execution_gate({"symbol": "EURUSD", "timeframe": "1h"})

    assert passed is False
    assert report["blockers"][0]["name"] == "paper_label_count"
