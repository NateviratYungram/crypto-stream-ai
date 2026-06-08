import sqlite3

import chat_server


def _columns(db_path, table):
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_init_persistence_db_creates_core_tables_and_runs_migrations(tmp_path, monkeypatch):
    db_path = tmp_path / "persistence.db"
    fallback_path = tmp_path / "fallback.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, updated_at DATETIME)")
        conn.execute("CREATE TABLE watchlist (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, note TEXT)")
        conn.execute("CREATE TABLE paper_trades (id TEXT PRIMARY KEY, symbol TEXT)")
        conn.execute("CREATE TABLE telegram_user_profiles (chat_id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE telegram_trade_confirmations (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE telegram_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.execute("CREATE TABLE best_setup_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.execute("CREATE TABLE signal_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.execute("CREATE TABLE tactics_audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT)")
        conn.commit()

    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(fallback_path))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))

    chat_server.init_persistence_db()

    assert "last_message" in _columns(db_path, "sessions")
    assert {"role", "content", "metadata"}.issubset(_columns(db_path, "messages"))
    assert {"username", "email", "hashed_password"}.issubset(_columns(db_path, "users"))
    assert {"action", "volume", "sl", "tp"}.issubset(_columns(db_path, "trade_drafts"))
    assert {"entry_price", "tp1", "be_triggered"}.issubset(_columns(db_path, "active_trades"))
    assert {"balance", "equity", "drawdown"}.issubset(_columns(db_path, "daily_performance"))
    assert {"confidence", "reasoning"}.issubset(_columns(db_path, "tactics_audit_log"))
    assert {"condition", "price", "timeframe", "entry_source", "meta_json"}.issubset(_columns(db_path, "alerts"))
    assert {"win_rate", "score"}.issubset(_columns(db_path, "trade_reviews"))
    assert {"type", "detail", "time"}.issubset(_columns(db_path, "audit_activity"))
    assert {"quantity", "volume", "current_price", "exit_price", "signal_grade", "macro_bias"}.issubset(
        _columns(db_path, "paper_trades")
    )
    assert {"username", "preferred_symbols_json", "default_lot", "risk_pct"}.issubset(
        _columns(db_path, "telegram_user_profiles")
    )
    assert {"chat_id", "symbol", "side", "request_json", "result_json", "expires_at"}.issubset(
        _columns(db_path, "telegram_trade_confirmations")
    )
    assert {"chat_id", "username", "action", "message", "payload_json"}.issubset(
        _columns(db_path, "telegram_audit_log")
    )
    assert {"run_id", "decision_action", "outcome_24h", "evaluated_at"}.issubset(
        _columns(db_path, "best_setup_outcomes")
    )
    assert {"signal_id", "canonical_symbol", "graph_guard_json", "outcome_24h"}.issubset(
        _columns(db_path, "signal_snapshots")
    )


def test_persistence_conn_falls_back_when_primary_cannot_open(tmp_path, monkeypatch):
    primary_dir = tmp_path / "missing" / "nested"
    primary_path = primary_dir / "persistence.db"
    fallback_path = tmp_path / "fallback" / "persistence.db"

    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(primary_path))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(fallback_path))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(primary_path))
    monkeypatch.setattr(chat_server, "_ensure_persistence_db_path", lambda: None)

    with chat_server.get_persistence_conn() as conn:
        conn.execute("CREATE TABLE audit_activity (type TEXT, detail TEXT, time TEXT)")
        conn.execute("INSERT INTO audit_activity VALUES ('x', 'y', 'z')")
        conn.commit()

    assert chat_server._ACTIVE_PERSISTENCE_DB == str(fallback_path)
    assert fallback_path.exists()


def test_append_audit_event_truncates_detail_and_swallows_db_errors(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    chat_server._append_audit_event("INFO", "x" * 700)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT type, detail FROM audit_activity ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("INFO", "x" * 500)

    monkeypatch.setattr(
        chat_server,
        "get_persistence_conn",
        lambda: (_ for _ in ()).throw(RuntimeError("db closed")),
    )
    chat_server._append_audit_event("INFO", "ignored")
