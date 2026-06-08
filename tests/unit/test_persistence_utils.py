import sqlite3

from intelligence import persistence_utils as pu


def create_db(tmp_path):
    db_path = tmp_path / "persistence.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE trade_drafts (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                symbol TEXT,
                action TEXT,
                volume REAL,
                sl REAL,
                tp REAL,
                comment TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE active_trades (
                ticket INTEGER PRIMARY KEY,
                symbol TEXT,
                entry_price REAL,
                tp1 REAL,
                be_triggered INTEGER,
                draft_id TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE sniper_audit_log (
                symbol TEXT,
                confidence REAL,
                reasoning TEXT,
                price REAL,
                timestamp TEXT
            )
            """
        )
        con.commit()
    return db_path


def test_drawdown_calculation():
    assert pu._calculate_drawdown(1000, 900) == 10.0
    assert pu._calculate_drawdown(0, 900) == 0


def test_save_get_and_delete_trade_draft(tmp_path, monkeypatch):
    db_path = create_db(tmp_path)
    monkeypatch.setattr(pu, "PERSISTENCE_DB", str(db_path))

    assert pu.save_trade_draft("draft1", "session1", "BTCUSD", "buy", 1.5, sl=95, tp=110, comment="test") is True
    row = pu.get_trade_draft("DRAFT1")
    assert row["symbol"] == "BTCUSD"
    assert row["action"] == "BUY"
    assert pu.delete_trade_draft("draft1") is True
    assert pu.get_trade_draft("draft1") is None


def test_register_get_and_mark_active_trade(tmp_path, monkeypatch):
    db_path = create_db(tmp_path)
    monkeypatch.setattr(pu, "PERSISTENCE_DB", str(db_path))

    assert pu.register_active_trade(101, "ETHUSD", 100.0, 110.0, "draft1") is True
    rows = pu.get_active_trades()
    assert len(rows) == 1
    assert rows[0]["ticket"] == 101
    assert pu.mark_trade_be_triggered(101) is True
    assert pu.get_active_trades() == []


def test_init_v6_tables_and_log_daily_balance(tmp_path, monkeypatch):
    db_path = create_db(tmp_path)
    monkeypatch.setattr(pu, "PERSISTENCE_DB", str(db_path))

    pu.init_v6_tables()
    assert pu.log_daily_balance(1000.0, 920.0) is True

    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT balance, equity, drawdown FROM daily_performance").fetchone()
    assert row == (1000.0, 920.0, 8.0)


def test_log_sniper_rejection_persists_upper_symbol(tmp_path, monkeypatch):
    db_path = create_db(tmp_path)
    monkeypatch.setattr(pu, "PERSISTENCE_DB", str(db_path))

    assert pu.log_sniper_rejection("btcusd", 0.72, "weak structure", price=100.5) is True

    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT symbol, confidence, reasoning, price FROM sniper_audit_log").fetchone()
    assert row == ("BTCUSD", 0.72, "weak structure", 100.5)


def test_failure_paths_return_safe_defaults(monkeypatch):
    monkeypatch.setattr(pu, "_connect", lambda row_factory=None: (_ for _ in ()).throw(sqlite3.OperationalError("db down")))

    assert pu.save_trade_draft("a", "b", "c", "buy", 1.0) is False
    assert pu.get_trade_draft("a") is None
    assert pu.delete_trade_draft("a") is False
    assert pu.register_active_trade(1, "BTCUSD", 1.0, 2.0, "d") is False
    assert pu.get_active_trades() == []
    assert pu.mark_trade_be_triggered(1) is False
    assert pu.log_daily_balance(100.0, 90.0) is False
    assert pu.log_sniper_rejection("BTCUSD", 0.5, "x") is False
