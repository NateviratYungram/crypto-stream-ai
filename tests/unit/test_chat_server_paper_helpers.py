import sqlite3

from chat_server_paper_helpers import _num, _paper_summary, _serialize_paper_trade


def _row_factory(data: dict):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    columns = ", ".join(f"{key} TEXT" for key in data.keys())
    conn.execute(f"CREATE TABLE sample ({columns})")
    conn.execute(
        f"INSERT INTO sample VALUES ({', '.join('?' for _ in data)})",
        [str(value) if value is not None else None for value in data.values()],
    )
    return conn, conn.execute("SELECT * FROM sample").fetchone()


def test_num_handles_none_and_bad_values():
    assert _num(None, 5.0) == 5.0
    assert _num("1.25") == 1.25
    assert _num("bad", 3.0) == 3.0


def test_serialize_paper_trade_for_open_and_closed_rows():
    open_conn, open_row = _row_factory(
        {
            "id": "1",
            "symbol": "BTCUSD",
            "side": "BUY",
            "volume": "2",
            "quantity": None,
            "entry_price": "100",
            "current_price": "110",
            "exit_price": None,
            "pnl_usd": None,
            "pnl": None,
            "status": "OPEN",
            "opened_at": "now",
            "closed_at": None,
            "ml_score": "70",
            "outcome": None,
            "sl": "95",
            "tp": "120",
            "signal_grade": "A",
            "macro_bias": "BULLISH",
            "features_json": '{"rsi": 30}',
            "entry_source": "scanner",
            "entry_reason": "signal",
            "close_reason": None,
            "label_source": "paper",
        }
    )
    closed_conn, closed_row = _row_factory(
        {
            "id": "2",
            "symbol": "ETHUSD",
            "side": "SELL",
            "volume": None,
            "quantity": "1.5",
            "entry_price": "200",
            "current_price": "180",
            "exit_price": "180",
            "pnl_usd": "15",
            "pnl": None,
            "status": "CLOSED",
            "opened_at": "then",
            "closed_at": "later",
            "ml_score": None,
            "outcome": "WIN",
            "sl": None,
            "tp": None,
            "signal_grade": None,
            "macro_bias": None,
            "features_json": "bad-json",
            "entry_source": None,
            "entry_reason": None,
            "close_reason": "tp",
            "label_source": None,
        }
    )
    plain_conn, plain_row = _row_factory(
        {
            "id": "3",
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": "1",
            "quantity": None,
            "entry_price": "50",
            "current_price": "40",
            "exit_price": None,
            "pnl_usd": None,
            "pnl": None,
            "status": "OPEN",
            "opened_at": "now",
            "closed_at": None,
            "ml_score": None,
            "outcome": None,
            "sl": None,
            "tp": None,
            "signal_grade": None,
            "macro_bias": None,
            "features_json": None,
            "entry_source": None,
            "entry_reason": None,
            "close_reason": None,
            "label_source": None,
        }
    )

    open_trade = _serialize_paper_trade(open_row)
    closed_trade = _serialize_paper_trade(closed_row)
    plain_trade = _serialize_paper_trade(plain_row)

    assert open_trade["pnl_usd"] == 20.0
    assert open_trade["features"] == {"rsi": 30}
    assert open_trade["stop_loss"] == 95.0
    assert closed_trade["pnl_usd"] == 15.0
    assert closed_trade["features"] is None
    assert closed_trade["quantity"] == 1.5
    assert plain_trade["features"] is None
    open_conn.close()
    closed_conn.close()
    plain_conn.close()

    open_conn.close()
    closed_conn.close()
    plain_conn.close()


def test_paper_summary_computes_counts_and_profit_factor(monkeypatch):
    monkeypatch.setenv("ML_READY_MIN_PAPER_LABELS", "10")
    open_trades = [{"symbol": "BTCUSD", "entry_source": "scanner", "pnl_usd": 5}]
    closed_trades = [
        {"symbol": "BTCUSD", "entry_source": "scanner", "pnl_usd": 10, "outcome": "WIN"},
        {"symbol": "ETHUSD", "entry_source": "manual_ui", "pnl_usd": -4, "outcome": "LOSS"},
        {"symbol": "SOLUSD", "entry_source": "manual_ui", "pnl_usd": 0, "outcome": None},
    ]

    summary = _paper_summary(open_trades, closed_trades)

    assert summary["open_count"] == 1
    assert summary["closed_count"] == 3
    assert summary["label_count"] == 2
    assert summary["labels_remaining"] == 8
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["profit_factor"] == 2.5
    assert summary["closed_pnl_usd"] == 6.0
    assert summary["open_unrealized_pnl_usd"] == 5.0


def test_paper_summary_uses_infinite_like_profit_factor_when_no_losses(monkeypatch):
    monkeypatch.setenv("ML_READY_MIN_PAPER_LABELS", "2")
    summary = _paper_summary(
        [],
        [{"symbol": "BTCUSD", "entry_source": "scanner", "pnl_usd": 12, "outcome": "WIN"}],
    )

    assert summary["profit_factor"] == 999.0
    assert summary["win_rate"] == 1.0
