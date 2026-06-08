import os
import sys
import sqlite3
import asyncio
from pathlib import Path
from types import SimpleNamespace

import chat_server


def test_check_socket_success_and_error(monkeypatch):
    class DummyConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: DummyConn())
    ok = chat_server._check_socket("kafka", "localhost:9092", timeout=0.1)
    assert ok == {"status": "ok", "target": "localhost:9092"}

    def _boom(*args, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr("socket.create_connection", _boom)
    err = chat_server._check_socket("kafka", "localhost:9092", timeout=0.1)
    assert err["status"] == "error"
    assert "refused" in err["error"]


def test_check_datalake_handles_missing_and_valid_partition(tmp_path, monkeypatch):
    missing_root = tmp_path / "missing"
    monkeypatch.setenv("DATALAKE_READ_PATH", str(missing_root))
    missing = chat_server._check_datalake()
    assert missing["status"] == "error"

    root = tmp_path / "lake"
    now = chat_server.datetime.now(chat_server.timezone.utc)
    partition = root / f"year={now:%Y}" / f"month={now:%m}" / f"day={now:%d}"
    partition.mkdir(parents=True, exist_ok=True)
    sample = partition / "chunk.parquet"
    sample.write_bytes(b"PAR1")
    monkeypatch.setenv("DATALAKE_READ_PATH", str(root))
    ok = chat_server._check_datalake()
    assert ok["status"] == "ok"
    assert ok["sample_file"] == "chunk.parquet"
    assert ok["partition"].startswith(f"year={now:%Y}")


def test_build_system_readiness_aggregates_checks(monkeypatch):
    class FakeConn:
        def cursor(self):
            return self

        def execute(self, _sql):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def close(self):
            return None

    monkeypatch.setattr(chat_server, "_readiness_db_connect", lambda: FakeConn())
    monkeypatch.setattr(chat_server, "_get_schema", lambda: {"tools": []})
    monkeypatch.setattr(chat_server, "_check_socket", lambda *args, **kwargs: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_check_rag_vector", lambda: {"status": "ok", "embedded_chunks": 10})
    monkeypatch.setattr(chat_server, "_check_anomaly_pipeline", lambda hours=72: {"status": "ok", "event_count": 2})
    monkeypatch.setattr(chat_server, "_check_datalake", lambda: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_check_lineage", lambda: {"status": "ok"})
    monkeypatch.setattr(chat_server.notifier, "telegram_status", lambda: {"configured": True, "chat_id": "1"})
    monkeypatch.setattr(
        chat_server,
        "_check_mt5_runtime",
        lambda: {"status": "ok", "connected": True, "live_execution_enabled": True},
    )
    monkeypatch.setattr(
        chat_server,
        "_check_ai_trading_quality",
        lambda: {"status": "ok", "live_ready": True, "mode": "live"},
    )

    readiness = chat_server.build_system_readiness()
    assert readiness["status"] == "ok"
    assert readiness["overall_percent"] == 100
    assert readiness["ready_for_live_trading"] is True
    assert readiness["checks"]["telegram"]["status"] == "ok"


def test_telegram_profile_get_and_save_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "telegram.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    default_profile = chat_server._telegram_get_profile("42")
    assert default_profile["chat_id"] == "42"
    assert default_profile["language"] == "th"

    saved = chat_server._telegram_save_profile(
        "42",
        {
            "username": "alice",
            "first_name": "Alice",
            "preferred_symbols": ["btc", "eth", "BTC"],
            "risk_pct": 1.5,
            "language": "en",
            "answer_style": "detailed",
        },
    )
    loaded = chat_server._telegram_get_profile("42")

    assert saved["preferred_symbols"] == ["BTC", "ETH"]
    assert loaded["username"] == "alice"
    assert loaded["first_name"] == "Alice"
    assert loaded["preferred_symbols"] == ["BTC", "ETH"]
    assert loaded["risk_pct"] == 1.5
    assert loaded["language"] == "en"


def test_trade_graph_status_and_quote_helpers(tmp_path, monkeypatch):
    db_path = tmp_path / "graph.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            "INSERT INTO trade_graph_nodes (node_key, node_type, label, properties_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                "graph_meta:TRADE_GRAPH",
                "META",
                "graph",
                '{"version": 1}',
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO trade_graph_nodes (node_key, node_type, label, properties_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                "setup:BTC:LONG",
                "SETUP",
                "btc-long",
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO trade_graph_edges (source_key, target_key, edge_type, weight, evidence_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "setup:BTC:LONG",
                "graph_meta:TRADE_GRAPH",
                "RELATES_TO",
                0.8,
                "{}",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()

    status = chat_server._trade_graph_status()
    assert status["status"] == "OK"
    assert status["nodes"] >= 2
    assert status["edges"] == 1
    assert status["last_build"]["version"] == 1

    assert chat_server._normalize_quote_symbol("btcusd") == "BTC-USD"
    assert chat_server._normalize_quote_symbol("eurusd") == "EURUSD=X"
    assert chat_server._normalize_quote_symbol("xauusd") == "XAUUSD"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"price": "68123.45"}

    monkeypatch.setattr(chat_server.requests, "get", lambda *args, **kwargs: FakeResponse())
    assert chat_server._get_live_price("BTCUSDT") == 68123.45

    monkeypatch.setattr(chat_server.requests, "get", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(chat_server, "_cache_get", lambda key: {"BTC": {"price": 67000}} if key == "market_stocks_v2" else {})
    assert chat_server._get_live_price("BTCUSDT") == 67000.0

    monkeypatch.setattr(chat_server, "_cache_get", lambda key: {})
    monkeypatch.setattr(chat_server, "_yahoo_batch_quotes", lambda symbols: {"EURUSD=X": {"regularMarketPrice": 1.08}})
    assert chat_server._get_live_price("EURUSD") == 1.08


def test_readiness_helpers_and_formatter(monkeypatch):
    class FakeCursor:
        def __init__(self, dict_mode=False):
            self._step = 0
            self._dict_mode = dict_mode

        def execute(self, _sql, _params=None):
            self._step += 1
            return None

        def fetchone(self):
            if not self._dict_mode:
                return (8, 5)
            return {"event_count": 4}

        def fetchall(self):
            return [{"symbol": "BTCUSD", "count": 3}]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def cursor(self, *args, **kwargs):
            return FakeCursor(dict_mode=bool(kwargs.get("cursor_factory")))

        def close(self):
            return None

    monkeypatch.setattr(chat_server, "_readiness_db_connect", lambda: FakeConn())

    rag = chat_server._check_rag_vector()
    assert rag == {"status": "ok", "chunks": 8, "embedded_chunks": 5}

    anomaly = chat_server._check_anomaly_pipeline(hours=24)
    assert anomaly["status"] == "ok"
    assert anomaly["hours"] == 24
    assert anomaly["event_count"] == 4
    assert anomaly["top_symbols"] == [{"symbol": "BTCUSD", "count": 3}]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"namespaces": ["public", "ops"]}

    monkeypatch.setenv("MARQUEZ_URL", "http://lineage.local")
    monkeypatch.setattr(chat_server.requests, "get", lambda *args, **kwargs: FakeResponse())
    lineage = chat_server._check_lineage()
    assert lineage == {"status": "ok", "url": "http://lineage.local", "namespace_count": 2}

    readiness = {
        "core_ready": True,
        "ready_for_notifications": False,
        "ready_for_live_trading": False,
        "ready_for_mt5_execution": True,
        "overall_percent": 78,
        "checks": {
            "anomaly_pipeline": anomaly,
            "rag_vector": rag,
            "data_lake": {"sample_file": "latest.parquet"},
            "mt5": {"connected": True, "live_execution_enabled": True},
            "ai_trading_quality": {"blockers": ["paper labels missing"]},
        },
    }
    formatted = chat_server.format_readiness_for_chat(readiness)
    assert "78%" in formatted
    assert "latest.parquet" in formatted
    assert "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID" in formatted
    assert "MT5 bridge" in formatted
    assert "paper labels missing" in formatted

    disabled_live = chat_server.format_readiness_for_chat(
        {
            **readiness,
            "ready_for_mt5_execution": False,
            "checks": {
                **readiness["checks"],
                "mt5": {"connected": True, "live_execution_enabled": False},
            },
        }
    )
    assert "MT5_BRIDGE_ENABLE_LIVE_TRADING=1" in disabled_live

    disconnected = chat_server.format_readiness_for_chat(
        {
            **readiness,
            "ready_for_mt5_execution": False,
            "checks": {
                **readiness["checks"],
                "mt5": {"connected": False, "error": "bridge down"},
            },
        }
    )
    assert "bridge down" in disconnected


def test_check_mt5_runtime_cache_direct_and_error_paths(monkeypatch):
    original_cache = dict(chat_server.GLOBAL_ACCOUNT_CACHE)
    try:
        monkeypatch.setattr(chat_server.time, "time", lambda: 1000.0)
        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        chat_server.GLOBAL_ACCOUNT_CACHE.update(
            {
                "summary": {"balance": 1200, "bridge_live_trading_enabled": True},
                "positions": [{"symbol": "BTCUSD"}],
                "updated_at": 980.0,
            }
        )
        cached = chat_server._check_mt5_runtime()
        assert cached["status"] == "ok"
        assert cached["source"] == "cache"
        assert cached["positions_count"] == 1

        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        monkeypatch.setitem(
            sys.modules,
            "intelligence.mt5_connector",
            SimpleNamespace(
                get_mt5_account_info=lambda: {"balance": 2500, "bridge_live_trading_enabled": False},
                get_mt5_positions=lambda: [{"symbol": "ETHUSD"}, {"symbol": "XAUUSD"}],
            ),
        )
        direct = chat_server._check_mt5_runtime()
        assert direct["status"] == "ok"
        assert direct["source"] == "direct"
        assert direct["positions_count"] == 2
        assert chat_server.GLOBAL_ACCOUNT_CACHE["summary"]["balance"] == 2500

        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        monkeypatch.setitem(
            sys.modules,
            "intelligence.mt5_connector",
            SimpleNamespace(
                get_mt5_account_info=lambda: {"error": "terminal offline"},
                get_mt5_positions=lambda: [],
            ),
        )
        not_ready = chat_server._check_mt5_runtime()
        assert not_ready == {"status": "not_ready", "connected": False, "error": "terminal offline"}

        def _explode():
            raise RuntimeError("mt5 boom")

        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        monkeypatch.setitem(
            sys.modules,
            "intelligence.mt5_connector",
            SimpleNamespace(get_mt5_account_info=_explode, get_mt5_positions=lambda: []),
        )
        exploded = chat_server._check_mt5_runtime()
        assert exploded["status"] == "not_ready"
        assert exploded["connected"] is False
        assert "mt5 boom" in exploded["error"]
    finally:
        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        chat_server.GLOBAL_ACCOUNT_CACHE.update(original_cache)


def test_daily_risk_guard_and_assertion_block(tmp_path, monkeypatch):
    db_path = tmp_path / "risk.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    monkeypatch.setenv("DAILY_LOSS_LIMIT_PCT", "2.0")
    monkeypatch.setenv("MAX_DAILY_TRADES", "2")
    chat_server.init_persistence_db()

    today = chat_server.datetime.now(chat_server.timezone.utc).strftime("%Y-%m-%dT09:00:00+00:00")
    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, quantity, entry_price, pnl_usd, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("t1", "BTCUSD", "BUY", 1, 68000, -30, "CLOSED", today, today),
        )
        conn.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, quantity, entry_price, pnl_usd, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("t2", "ETHUSD", "SELL", 1, 3500, -10, "CLOSED", today, today),
        )
        conn.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, quantity, entry_price, status, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("t3", "XAUUSD", "BUY", 1, 2300, "OPEN", today),
        )
        conn.commit()

    original_cache = dict(chat_server.GLOBAL_ACCOUNT_CACHE)
    try:
        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        chat_server.GLOBAL_ACCOUNT_CACHE["summary"] = {"balance": 1000}
        guard = chat_server._daily_risk_guard(chat_id="99")
        assert guard["status"] == "blocked"
        assert guard["paper_pnl_usd_today"] == -40.0
        assert guard["opened_trades_today"] == 3
        assert guard["open_trades"] == 1
        assert len(guard["blockers"]) >= 2

        try:
            chat_server._assert_daily_risk_guard_allows("OPEN_POSITION", chat_id="99")
            raise AssertionError("expected risk guard to block")
        except chat_server.HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail["status"] == "GUARD_BLOCKED"
            assert exc.detail["action"] == "OPEN_POSITION"
            assert exc.detail["guard"]["status"] == "blocked"
    finally:
        chat_server.GLOBAL_ACCOUNT_CACHE.clear()
        chat_server.GLOBAL_ACCOUNT_CACHE.update(original_cache)


def test_query_trade_graph_uses_outcomes_and_paper_trade_fallback(tmp_path, monkeypatch):
    db_path = tmp_path / "query.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    monkeypatch.setattr(
        chat_server,
        "_setup_feedback_summary",
        lambda limit=500: {"score_adjustments": {"BTCUSD:BUY": 0.25}},
    )

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO best_setup_outcomes
            (run_id, symbol, side, score, created_at, outcome_4h, return_4h)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("run-1", "BTCUSD", "BUY", 0.91, "2026-06-01T00:00:00+00:00", "WIN", 0.035),
        )
        conn.execute(
            "INSERT INTO trade_graph_nodes (node_key, node_type, label, properties_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("setup:BTCUSD:BUY", "SETUP", "btc-buy", "{}", "2026-06-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO trade_graph_edges (source_key, target_key, edge_type, weight, evidence_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "setup:BTCUSD:BUY",
                "signal:momentum",
                "SUPPORTS",
                0.8,
                '{"reason":"test"}',
                "2026-06-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, entry_price, pnl_usd, status, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("paper-1", "ETHUSD", "SELL", 1, 3600, 12, "CLOSED", "2026-06-01T00:00:00+00:00", "2026-06-01T02:00:00+00:00"),
        )
        conn.commit()

    outcomes = chat_server._query_trade_graph(symbol="btcusdt", side="buy", limit=3)
    assert outcomes["status"] == "OK"
    assert outcomes["query"]["symbol"] == "BTCUSD"
    assert outcomes["setups"][0]["setup"] == "BTCUSD:BUY"
    assert outcomes["setups"][0]["feedback_adjustment"] == 0.25
    assert outcomes["setups"][0]["edges"][0]["edge_type"] == "SUPPORTS"

    fallback = chat_server._query_trade_graph(symbol="ethusd", side="sell", limit=3)
    assert fallback["status"] == "OK"
    assert fallback["setups"][0]["setup"] == "ETHUSD:SELL"
    assert fallback["setups"][0]["source"] == "paper_trades_fallback"
    assert fallback["setups"][0]["win_rate_4h"] == 1.0


def test_best_setup_metrics_build_trade_memory_and_feedback_wrappers(tmp_path, monkeypatch):
    real_feedback_summary = chat_server._setup_feedback_summary
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO best_setup_outcomes
            (run_id, symbol, side, score, decision_action, created_at, outcome_4h, return_4h)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("best-1", "BTC", "BUY", 0.88, "ENTER_NOW", "2026-06-01T00:00:00+00:00", "WIN", 0.02),
        )
        conn.execute(
            """
            INSERT INTO telegram_setup_feedback
            (chat_id, symbol, side, rating, source, score, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("42", "BTC", "BUY", "GOOD", "tg", 0.9, "{}", "2026-06-01T01:00:00+00:00"),
        )
        conn.commit()

    monkeypatch.setattr(chat_server, "_evaluate_best_setup_outcomes", lambda limit=120: {"checked": 1, "updated": 1})
    monkeypatch.setattr(chat_server, "BEST_OUTCOME_HORIZONS", {"4h": 4})

    metrics = chat_server._best_setup_metrics(limit=20, evaluate=True)
    assert metrics["total_snapshots"] == 1
    assert metrics["evaluation"]["updated"] == 1
    assert metrics["by_symbol"]["BTC"]["evaluated_4h"] == 1

    feedback = chat_server._setup_feedback_summary(chat_id="42", limit=10)
    assert feedback["available"] is True
    assert feedback["total"] == 1
    assert feedback["by_symbol_side"]["BTC:BUY"]["count"] == 1

    monkeypatch.setattr(chat_server, "_best_setup_metrics", lambda limit=500, evaluate=False: metrics)
    monkeypatch.setattr(chat_server, "_setup_feedback_summary", lambda limit=300: feedback)
    monkeypatch.setattr(
        chat_server,
        "_daily_risk_guard",
        lambda chat_id=None: {"status": "ok", "paper_pnl_usd_today": 15.0, "opened_trades_today": 1, "max_daily_trades": 10, "open_trades": 0, "blockers": []},
    )
    document = chat_server._build_trade_memory_document()
    assert "CryptoStream AI trade memory" in document
    assert "BTC" in document
    assert "GOOD" in document

    monkeypatch.setattr(chat_server, "_setup_feedback_summary", real_feedback_summary)
    monkeypatch.setattr(chat_server, "get_persistence_conn", lambda: (_ for _ in ()).throw(RuntimeError("db offline")))
    failed_feedback = chat_server._setup_feedback_summary(limit=5)
    assert failed_feedback["available"] is False
    assert "db offline" in failed_feedback["error"]
    assert "diagnostics unavailable" in chat_server._telegram_format_feedback().lower()


def test_sync_trade_memory_to_rag_skip_success_and_error(monkeypatch):
    original_state = dict(chat_server._trade_memory_sync_state)
    original_rag = sys.modules.get("intelligence.rag")
    try:
        chat_server._trade_memory_sync_state.clear()
        chat_server._trade_memory_sync_state.update({"last_sync_epoch": 100.0, "last_sync_at": "2026-06-01T00:00:00+00:00", "last_result": {"chunks": 2}})
        monkeypatch.setattr(chat_server.time, "time", lambda: 150.0)
        skipped = chat_server._sync_trade_memory_to_rag(force=False)
        assert skipped["status"] == "SKIPPED"
        assert skipped["last_result"] == {"chunks": 2}

        monkeypatch.setattr(chat_server.time, "time", lambda: 5000.0)
        monkeypatch.setattr(chat_server, "_build_trade_memory_document", lambda: "memory snapshot")

        def _ingest_ok(**kwargs):
            assert kwargs["source_uri"] == "system://cryptostream/trade-memory"
            assert kwargs["content"] == "memory snapshot"
            return {"chunks": 3, "document_id": "doc-1"}

        monkeypatch.setitem(sys.modules, "intelligence.rag", SimpleNamespace(ingest_knowledge_document=_ingest_ok))
        success = chat_server._sync_trade_memory_to_rag(force=True)
        assert success["status"] == "OK"
        assert success["result"]["chunks"] == 3
        assert chat_server._trade_memory_sync_state["last_error"] is None

        def _ingest_fail(**kwargs):
            raise RuntimeError("rag down")

        monkeypatch.setitem(sys.modules, "intelligence.rag", SimpleNamespace(ingest_knowledge_document=_ingest_fail))
        failed = chat_server._sync_trade_memory_to_rag(force=True)
        assert failed == {"status": "ERROR", "error": "rag down", "no_extra_embedding_cost": True}
        assert chat_server._trade_memory_sync_state["last_error"] == "rag down"
    finally:
        chat_server._trade_memory_sync_state.clear()
        chat_server._trade_memory_sync_state.update(original_state)
        if original_rag is not None:
            sys.modules["intelligence.rag"] = original_rag
        else:
            sys.modules.pop("intelligence.rag", None)


def test_trade_graph_context_and_open_best_paper_text_wrappers(monkeypatch):
    monkeypatch.setattr(chat_server, "_telegram_extract_symbol", lambda text, default="": "btcusdt")
    monkeypatch.setattr(chat_server, "_canonical_trade_symbol", lambda symbol: "BTCUSD" if symbol else "")

    calls = []

    def _query(symbol=None, side=None, limit=5):
        calls.append((symbol, side, limit))
        if symbol == "BTCUSD":
            return {"status": "OK", "setups": [], "summary": {"graph_status": {"status": "EMPTY"}}}
        return {
            "status": "OK",
            "setups": [{"setup": "ETHUSD:BUY", "snapshots": 4, "evaluated_4h": 3, "win_rate_4h": 0.6667, "avg_return_4h": 0.01, "feedback_adjustment": 0.05}],
            "summary": {"graph_status": {"status": "OK"}},
        }

    monkeypatch.setattr(chat_server, "_query_trade_graph", _query)
    context = chat_server._trade_graph_context_for_query("should we buy now?")
    assert context["status"] == "OK"
    assert context["symbol"] == "BTCUSD"
    assert context["side"] == "BUY"
    assert "no exact graph history" in context["fallback_reason"]
    assert context["top_setups"][0]["setup"] == "ETHUSD:BUY"
    assert calls == [("BTCUSD", "BUY", 5), (None, "BUY", 5)]

    monkeypatch.setattr(chat_server, "_query_trade_graph", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("graph boom")))
    error_context = chat_server._trade_graph_context_for_query("sell btc")
    assert error_context["status"] == "ERROR"
    assert error_context["symbol"] == "BTCUSD"
    assert "graph boom" in error_context["error"]

    monkeypatch.setattr(chat_server, "_open_best_paper_evidence", lambda chat_id=None: {"status": "OPENED", "opened": {"trade_id": 9, "volume": 0.02}, "setup": {"symbol": "BTC", "side": "BUY", "entry_price": 65000}, "best_alternative": {"best": {"mode": "WATCH", "reason": "fine"}}})
    opened_text = chat_server._telegram_open_best_paper_text("42")
    assert "Opened best paper evidence trade." in opened_text

    monkeypatch.setattr(chat_server, "_open_best_paper_evidence", lambda chat_id=None: (_ for _ in ()).throw(chat_server.HTTPException(status_code=409, detail={"status": "BLOCKED", "message": "risk cap", "guard": {"status": "GUARD_BLOCKED", "blockers": ["cap"]}})))
    blocked_text = chat_server._telegram_open_best_paper_text("42")
    assert "Best paper trade blocked safely." in blocked_text
    assert "risk cap" in blocked_text

    monkeypatch.setattr(chat_server, "_open_best_paper_evidence", lambda chat_id=None: (_ for _ in ()).throw(RuntimeError("unexpected open failure")))
    failed_text = chat_server._telegram_open_best_paper_text("42")
    assert failed_text == "Open best paper failed: unexpected open failure"


def test_trade_graph_guard_and_assert_wrapper_paths(monkeypatch):
    monkeypatch.setattr(chat_server, "_canonical_trade_symbol", lambda symbol: str(symbol or "").upper().strip())
    monkeypatch.setattr(chat_server, "TRADE_GRAPH_GUARD_MIN_EVALUATED", 5)
    monkeypatch.setattr(chat_server, "TRADE_GRAPH_GUARD_MIN_WIN_RATE", 0.35)
    monkeypatch.setattr(chat_server, "TRADE_GRAPH_GUARD_MIN_AVG_RETURN", -0.005)
    monkeypatch.setattr(chat_server, "BEST_SETUP_QUARANTINE_ADJUSTMENT", -0.12)

    invalid = chat_server._trade_graph_guard("", "")
    assert invalid["status"] == "INSUFFICIENT_DATA"
    assert invalid["action"] == "ALLOW"

    monkeypatch.setattr(
        chat_server,
        "_query_trade_graph",
        lambda symbol=None, side=None, limit=5: {
            "query": {"symbol": symbol, "side": side},
            "setups": [{"setup": f"{symbol}:{side}", "evaluated_4h": 12, "win_rate_4h": 0.61, "avg_return_4h": 0.01, "feedback_adjustment": 0.02}],
        },
    )
    ok = chat_server._trade_graph_guard("btcusd", "buy")
    assert ok["status"] == "OK"
    assert ok["allowed"] is True
    assert ok["symbol"] == "BTCUSD"

    monkeypatch.setattr(chat_server, "_query_trade_graph", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("graph offline")))
    errored = chat_server._trade_graph_guard("ethusd", "sell")
    assert errored["status"] == "ERROR"
    assert errored["action"] == "ALLOW_WITH_CAUTION"
    assert errored["warnings"] == ["graph offline"]

    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"status": "OK", "blockers": [], "allowed": True})
    assert chat_server._assert_trade_graph_guard_allows("BTCUSD", "BUY", "OPEN")["status"] == "OK"

    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"status": "BLOCKED", "blockers": ["bad history"], "allowed": False})
    try:
        chat_server._assert_trade_graph_guard_allows("BTCUSD", "BUY", "OPEN")
        raise AssertionError("expected graph guard block")
    except chat_server.HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["status"] == "GRAPH_GUARD_BLOCKED"
        assert exc.detail["action"] == "OPEN"
        assert exc.detail["guard"]["blockers"] == ["bad history"]


def test_telegram_trade_graph_why_setup_and_best_alternative_wrappers(monkeypatch):
    monkeypatch.setattr(chat_server, "_canonical_trade_symbol", lambda symbol: {"btc": "BTCUSD", "gold": "GOLD"}.get(str(symbol or "").lower().strip(), str(symbol or "").upper().strip()))
    monkeypatch.setattr(chat_server, "_telegram_extract_symbol", lambda text, default="": "gold" if "gold" in str(text).lower() else "btc")
    monkeypatch.setattr(chat_server, "_trade_symbol_aliases", lambda symbol: [symbol, f"{symbol}_ALT"] if symbol else [])
    monkeypatch.setattr(chat_server, "TRADE_GRAPH_REBUILD_INTERVAL_SECONDS", 1800)

    rebuild_calls = []
    statuses = [{"status": "EMPTY"}, {"status": "OK", "nodes": 7, "edges": 3, "last_build": {"best_snapshots": 2, "paper_trades": 1, "feedback_labels": 1}}]
    monkeypatch.setattr(chat_server, "_trade_graph_status", lambda: statuses.pop(0))
    monkeypatch.setattr(chat_server, "_build_trade_knowledge_graph", lambda limit=1500: rebuild_calls.append(limit) or {"status": "OK"})
    monkeypatch.setattr(chat_server, "_query_trade_graph", lambda symbol=None, side=None, limit=5: {"setups": [{"setup": "GOLD:BUY", "evaluated_4h": 6, "win_rate_4h": 0.5, "avg_return_4h": 0.01, "feedback_adjustment": 0.1}], "summary": {"graph_status": {"status": "OK"}}})
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"status": "INSUFFICIENT_DATA", "reason": "no exact graph history"} if symbol == "GOLD" else {"status": "OK", "reason": "fine"})

    tg_text = chat_server._telegram_format_trade_graph("/graph gold BUY")
    assert rebuild_calls == [1500]
    assert "AI Finance Agent: Graph RAG memory" in tg_text
    assert "GOLD BUY" in tg_text

    monkeypatch.setattr(chat_server, "_trade_graph_status", lambda: {"status": "DOWN"})
    monkeypatch.setattr(chat_server, "_build_trade_knowledge_graph", lambda limit=1500: (_ for _ in ()).throw(RuntimeError("rebuild failed")))
    unavailable = chat_server._telegram_format_trade_graph("/graph btc buy")
    assert unavailable == "Trade Graph RAG unavailable: rebuild failed"

    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"symbol": symbol, "action": "BLOCK_TRADE", "status": "BLOCKED", "reason": "bad graph history", "evaluated_4h": 14, "win_rate_4h": 0.25, "avg_return_4h": -0.01, "blockers": ["low win"], "warnings": ["thin sample"]})
    monkeypatch.setattr(chat_server, "_query_trade_graph", lambda symbol=None, side=None, limit=3: {"setups": [{"setup": "BTCUSD:BUY", "snapshots": 22}]})
    monkeypatch.setattr(chat_server, "_daily_risk_guard", lambda chat_id=None: {"status": "WATCH", "opened_trades_today": 2, "max_daily_trades": 5, "blockers": ["risk cap"], "warnings": ["drawdown rising"]})
    monkeypatch.setattr(chat_server, "_signal_snapshot_metrics", lambda limit=500, evaluate=False: {"by_setup": {"BTCUSD:BUY": {"signals": 7, "evaluated_4h": 4, "win_rate_4h": 0.5}}})
    why_text = chat_server._telegram_format_why_setup("why btc buy", chat_id="42")
    assert "Why: BTCUSD:BUY" in why_text
    assert "BLOCK_TRADE" in why_text
    assert "Signal memory: signals=7" in why_text

    monkeypatch.setattr(chat_server, "TRADE_GRAPH_GUARD_MIN_EVALUATED", 5)
    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: {"preferred_symbols": ["btc"]})
    monkeypatch.setattr(chat_server, "_signal_snapshot_metrics", lambda limit=1000, evaluate=False: {"by_setup": {"BTCUSD:BUY": {"evaluated_4h": 3, "signals": 5}}})
    monkeypatch.setattr(chat_server, "_daily_risk_guard", lambda chat_id=None: {"status": "OK", "blockers": []})
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"symbol": symbol, "status": "OK", "evaluated_4h": 10, "win_rate_4h": 0.6, "avg_return_4h": 0.01, "reason": "strong graph"} if side == "BUY" else {"symbol": symbol, "status": "INSUFFICIENT_DATA", "evaluated_4h": 0, "reason": "collect evidence"})

    payload = chat_server._best_alternative_candidates("42")
    assert payload["decision"] == "TRADE"
    assert payload["best"]["symbol"] == "BTCUSD"
    assert payload["best"]["side"] == "BUY"

    best_text = chat_server._telegram_format_best_alternative("42")
    assert "AI Finance Agent: Best Alternative" in best_text
    assert "BTCUSD BUY" in best_text

    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: (_ for _ in ()).throw(RuntimeError("no profile")))
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"symbol": symbol, "status": "INSUFFICIENT_DATA", "evaluated_4h": 0, "reason": "collect evidence"})
    fallback_payload = chat_server._best_alternative_candidates("42")
    assert fallback_payload["decision"] == "PAPER_ONLY"


def test_open_best_paper_evidence_precheck_and_cooldown_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "openbest.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    monkeypatch.setattr(chat_server, "_best_alternative_candidates", lambda chat_id=None: {"decision": "NO_TRADE", "reason": "risk cap"})
    monkeypatch.setattr(chat_server, "_helper_precheck_open_best_paper_payload", lambda payload: {"status": "NO_TRADE", "message": "risk cap"})
    assert chat_server._open_best_paper_evidence("42") == {"status": "NO_TRADE", "message": "risk cap"}

    monkeypatch.setattr(chat_server, "_best_alternative_candidates", lambda chat_id=None: {"best": {"mode": "WATCH", "reason": "fine"}})
    monkeypatch.setattr(
        chat_server,
        "_helper_precheck_open_best_paper_payload",
        lambda payload: {"status": "READY", "symbol": "BTCUSD", "side": "BUY", "best": {"mode": "WATCH", "reason": "fine"}},
    )
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action, chat_id=None: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_assert_trade_graph_guard_allows", lambda symbol, side, action: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_auto_paper_status", lambda: {"cooldown_minutes": 30})
    monkeypatch.setattr(chat_server, "_serialize_paper_trade", lambda row: {"id": row["id"], "symbol": row["symbol"], "side": row["side"]})

    recent_time = "2099-01-01T00:00:00+00:00"
    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, entry_price, status, opened_at, closed_at, entry_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("rb1", "BTCUSD", "BUY", 1, 65000, "CLOSED", recent_time, recent_time, "bestalt_paper_evidence"),
        )
        conn.commit()

    cooldown = chat_server._open_best_paper_evidence("42")
    assert cooldown["status"] == "COOLDOWN"
    assert cooldown["trade"]["id"] == "rb1"


def test_open_best_paper_evidence_existing_recent_trade_and_price_unavailable(tmp_path, monkeypatch):
    db_path = tmp_path / "openbest2.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    monkeypatch.setattr(chat_server, "_best_alternative_candidates", lambda chat_id=None: {"best": {"mode": "WATCH", "reason": "fine"}})
    monkeypatch.setattr(
        chat_server,
        "_helper_precheck_open_best_paper_payload",
        lambda payload: {"status": "READY", "symbol": "ETHUSD", "side": "SELL", "best": {"mode": "WATCH", "reason": "fine"}},
    )
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action, chat_id=None: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_assert_trade_graph_guard_allows", lambda symbol, side, action: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_auto_paper_status", lambda: {"cooldown_minutes": 30, "volume": 0.02})
    monkeypatch.setattr(chat_server, "_serialize_paper_trade", lambda row: {"id": row["id"], "symbol": row["symbol"], "side": row["side"], "status": row["status"]})

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, entry_price, status, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("op1", "ETHUSD", "SELL", 1, 3500, "OPEN", "2099-01-01T00:00:00+00:00"),
        )
        conn.commit()

    already_open = chat_server._open_best_paper_evidence("42")
    assert already_open["status"] == "ALREADY_OPEN"
    assert already_open["trade"]["id"] == "op1"

    with chat_server.get_persistence_conn() as conn:
        conn.execute("DELETE FROM paper_trades")
        conn.commit()

    monkeypatch.setattr(chat_server, "_recent_trade_exists", lambda symbol, cooldown_minutes: True)
    symbol_cooldown = chat_server._open_best_paper_evidence("42")
    assert symbol_cooldown["status"] == "COOLDOWN"
    assert "ETHUSD" in symbol_cooldown["message"]

    monkeypatch.setattr(chat_server, "_recent_trade_exists", lambda symbol, cooldown_minutes: False)
    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: {"default_lot": 0.03})
    monkeypatch.setattr(chat_server, "_telegram_tactics_symbol", lambda symbol: f"{symbol}.m")
    monkeypatch.setattr(chat_server, "_helper_resolve_best_paper_volume", lambda **kwargs: 0.03)
    monkeypatch.setattr(chat_server, "_record_signal_snapshot", lambda *args, **kwargs: {"status": "OK"})
    monkeypatch.setattr(chat_server, "_telegram_resolve_paper_entry_price", lambda symbol, side, fallback_price=None: 0.0)
    monkeypatch.setitem(sys.modules, "intelligence.tools.market_tools", SimpleNamespace(get_trading_tactics=lambda symbol: {"price": 123.0}))

    unavailable = chat_server._open_best_paper_evidence("42")
    assert unavailable["status"] == "PRICE_UNAVAILABLE"
    assert unavailable["setup"]["price"] == 123.0


def test_open_best_paper_evidence_opened_with_levels_and_attach_failure(monkeypatch):
    monkeypatch.setattr(chat_server, "_best_alternative_candidates", lambda chat_id=None: {"best": {"mode": "TRADE_CANDIDATE", "reason": "strong graph"}})
    monkeypatch.setattr(
        chat_server,
        "_helper_precheck_open_best_paper_payload",
        lambda payload: {"status": "READY", "symbol": "BTCUSD", "side": "BUY", "best": {"mode": "TRADE_CANDIDATE", "reason": "strong graph"}},
    )
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action, chat_id=None: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_assert_trade_graph_guard_allows", lambda symbol, side, action: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_auto_paper_status", lambda: {"cooldown_minutes": 30, "volume": 0.01})

    class EmptyConn:
        def execute(self, *args, **kwargs):
            return self

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(chat_server, "get_persistence_conn", lambda: EmptyConn())
    monkeypatch.setattr(chat_server, "_recent_trade_exists", lambda symbol, cooldown_minutes: False)
    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: {"default_lot": 0.05})
    monkeypatch.setattr(chat_server, "_helper_resolve_best_paper_volume", lambda **kwargs: 0.05)
    monkeypatch.setattr(chat_server, "_telegram_tactics_symbol", lambda symbol: symbol)
    monkeypatch.setattr(chat_server, "_record_signal_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("snapshot boom")))
    monkeypatch.setattr(chat_server, "_telegram_resolve_paper_entry_price", lambda symbol, side, fallback_price=None: 65000.0)
    monkeypatch.setattr(chat_server, "_helper_best_paper_entry_reason", lambda best: "BestAlt evidence")
    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: {"trade_id": "t-open", "ml_snapshot_attached": False})
    monkeypatch.setattr(chat_server, "_daily_risk_guard", lambda chat_id=None: {"status": "ok"})
    monkeypatch.setitem(sys.modules, "intelligence.tools.market_tools", SimpleNamespace(get_trading_tactics=lambda symbol: {"price": 65000, "stop_loss": 64000, "take_profit_1": 67000}))
    monkeypatch.setitem(sys.modules, "intelligence.ml.outcome_tracker", SimpleNamespace(attach_sl_tp_features=lambda *args, **kwargs: None))

    opened = chat_server._open_best_paper_evidence("42", volume=0.05)
    assert opened["status"] == "OPENED"
    assert opened["opened"]["trade_id"] == "t-open"
    assert opened["opened"]["levels_attached"] is True
    assert opened["opened"]["stop_loss"] == 64000.0
    assert opened["setup"]["entry_price"] == 65000.0

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.outcome_tracker",
        SimpleNamespace(attach_sl_tp_features=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("attach failed"))),
    )
    failed_attach = chat_server._open_best_paper_evidence("42", volume=0.05)
    assert failed_attach["status"] == "OPENED"
    assert failed_attach["opened"]["levels_attached"] is False
    assert "attach failed" in failed_attach["opened"]["levels_error"]


def test_auto_paper_status_asset_class_and_recent_trade_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "autopaper.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    original_state = dict(chat_server._auto_paper_state)
    try:
        chat_server._auto_paper_state.update(
            {
                "enabled": True,
                "shadow_labeling_enabled": True,
                "symbols": ["BTCUSD", "GOLD"],
                "confidence_threshold": 0.72,
                "shadow_min_probability": 0.41,
                "shadow_label_max_age_minutes": 240,
                "volume": 0.03,
                "cooldown_minutes": 45,
                "max_open_positions": 7,
                "scan_interval_seconds": 60,
                "last_run_at": "2026-06-02T00:00:00+00:00",
                "last_error": None,
                "last_summary": {"opened": 1},
            }
        )
        status = chat_server._auto_paper_status()
        assert status["enabled"] is True
        assert status["shadow_labeling_enabled"] is True
        assert status["symbols"] == ["BTCUSD", "GOLD"]
        assert status["cooldown_minutes"] == 45
        assert status["last_summary"] == {"opened": 1}
    finally:
        chat_server._auto_paper_state.clear()
        chat_server._auto_paper_state.update(original_state)

    assert chat_server._symbol_asset_class("BTCUSD") == "CRYPTO"
    assert chat_server._symbol_asset_class("XAUUSD") == "MACRO"

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (id, symbol, side, quantity, entry_price, status, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("r1", "BTCUSD", "BUY", 1, 65000, "OPEN", "2099-01-01T00:00:00+00:00"),
        )
        conn.commit()

    assert chat_server._recent_trade_exists("BTCUSD", 30) is True
    assert chat_server._recent_trade_exists("ETHUSD", 30) is False


def test_auto_paper_performance_gate_and_expire_stale_labels(tmp_path, monkeypatch):
    db_path = tmp_path / "expire.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.performance_feedback",
        SimpleNamespace(paper_entry_performance_gate=lambda symbol, side, entry_source: {"ok": False, "blockers": [f"{symbol}:{side}:{entry_source}"]}),
    )
    blocked = chat_server._auto_paper_performance_gate("BTCUSD", "BUY", "auto_paper")
    assert blocked["ok"] is False
    assert blocked["blockers"] == ["BTCUSD:BUY:auto_paper"]

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.performance_feedback",
        SimpleNamespace(paper_entry_performance_gate=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("perf down"))),
    )
    degraded = chat_server._auto_paper_performance_gate("BTCUSD", "BUY", "auto_paper")
    assert degraded["ok"] is True
    assert degraded["warnings"] == ["performance_gate_unavailable:perf down"]

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, volume, entry_price, current_price, status, opened_at, entry_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s1", "BTCUSD", "BUY", 2, 2, 100, 100, "OPEN", "2000-01-01T00:00:00+00:00", "shadow_label"),
        )
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, volume, entry_price, current_price, status, opened_at, entry_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("s2", "ETHUSD", "SELL", 1, 1, 200, 200, "OPEN", "2000-01-01T00:00:00+00:00", "auto_paper"),
        )
        conn.commit()

    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: {"BTCUSD": 110.0, "ETHUSD": 180.0}.get(symbol, 0.0))
    audits = []
    monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: audits.append((event_type, detail)))
    monkeypatch.setattr(chat_server, "_ensure_trade_review_snapshots", lambda: audits.append(("SNAP", "done")))
    monkeypatch.setattr(chat_server, "_maybe_trigger_auto_retrain", lambda reason: {"triggered": True, "reason": reason})

    summary = chat_server._expire_stale_paper_labels(60)
    assert summary["closed_count"] == 2
    assert summary["closed"][0]["symbol"] == "BTCUSD"
    assert summary["auto_retrain"] == {"triggered": True, "reason": "paper_label_time_expiry"}
    assert audits[0][0] == "AUTO_PAPER"

    with chat_server.get_persistence_conn() as conn:
        rows = conn.execute("SELECT id, status, outcome, close_reason, label_source FROM paper_trades ORDER BY id").fetchall()
    assert [row["status"] for row in rows] == ["CLOSED", "CLOSED"]
    assert rows[0]["label_source"] == "time_expiry"


def test_expire_stale_labels_skips_when_no_exit_price(tmp_path, monkeypatch):
    db_path = tmp_path / "expire_skip.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades
            (id, symbol, side, quantity, volume, entry_price, current_price, status, opened_at, entry_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("sx", "XAUUSD", "BUY", 1, 1, 0, 0, "OPEN", "2000-01-01T00:00:00+00:00", "shadow_label"),
        )
        conn.commit()

    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 0.0)
    summary = chat_server._expire_stale_paper_labels(60)
    assert summary["closed_count"] == 0
    assert summary["skipped"] == [{"trade_id": "sx", "symbol": "XAUUSD", "reason": "no_exit_price"}]


def test_open_paper_trade_internal_validates_and_opens(tmp_path, monkeypatch):
    db_path = tmp_path / "paperopen.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    try:
        chat_server._open_paper_trade_internal("BTCUSD", "HOLD", 1)
        raise AssertionError("expected invalid side failure")
    except chat_server.HTTPException as exc:
        assert exc.status_code == 400
        assert "side must be BUY or SELL" in str(exc.detail)

    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", SimpleNamespace(ML_CORE_SYMBOLS={"BTCUSD", "ETHUSD"}))
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action: {"status": "ok", "action": action})
    monkeypatch.setattr(chat_server, "_assert_trade_graph_guard_allows", lambda symbol, side, action: {"status": "ok", "symbol": symbol, "side": side, "action": action})
    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 65000.0 if symbol == "BTCUSD" else 0.0)
    monkeypatch.setattr(chat_server, "_lookup_ai_score", lambda symbol: 0.44)
    monkeypatch.setattr(
        chat_server,
        "_capture_trade_ml_snapshot",
        lambda symbol, side, entry_price: {
            "sl": 64000.0,
            "tp": 67000.0,
            "ml_score": 0.82,
            "timeframe": "15m",
            "features": {"symbol": symbol},
        },
    )
    monkeypatch.setitem(sys.modules, "intelligence.ml.outcome_tracker", SimpleNamespace(attach_sl_tp_features=lambda *args, **kwargs: None))
    audits = []
    monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: audits.append((event_type, detail)))

    opened = chat_server._open_paper_trade_internal(" btcusd ", " buy ", 0.0, entry_source="manual_ui", entry_reason="unit test")
    assert opened["status"] == "opened"
    assert opened["entry_price"] == 65000.0
    assert opened["ml_snapshot_attached"] is True
    assert opened["focus_timeframe"] == "15m"
    assert opened["focus_symbol"] is True
    assert opened["contributes_to_core_dataset"] is True
    assert opened["entry_source"] == "manual_ui"
    assert audits[0][0] == "PAPER_TRADE"

    with chat_server.get_persistence_conn() as conn:
        row = conn.execute("SELECT symbol, side, quantity, volume, entry_source, entry_reason, ml_score FROM paper_trades").fetchone()
    assert row["symbol"] == "BTCUSD"
    assert row["side"] == "BUY"
    assert row["quantity"] == 1.0
    assert row["entry_source"] == "manual_ui"
    assert row["entry_reason"] == "unit test"
    assert row["ml_score"] == 0.82

    monkeypatch.setattr(chat_server, "_capture_trade_ml_snapshot", lambda symbol, side, entry_price: None)
    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 123.45)
    shadow_opened = chat_server._open_paper_trade_internal("gold", "SELL", 0.2, price=None, entry_source="shadow_label")
    assert shadow_opened["focus_symbol"] is False
    assert shadow_opened["ml_snapshot_attached"] is False

    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 0.0)
    try:
        chat_server._open_paper_trade_internal("XAUUSD", "BUY", 1, price=0.0)
        raise AssertionError("expected missing price failure")
    except chat_server.HTTPException as exc:
        assert exc.status_code == 400
        assert "Unable to resolve live price" in str(exc.detail)


def test_auto_paper_cycle_sync_and_shadow_paths(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "intelligence.tools.market_tools",
        SimpleNamespace(
            get_trading_tactics=lambda symbol: {
                "recommendation": "BUY",
                "ai_edge": {"signal_confidence": 0.9},
                "price": 101.0,
                "best_persona": "Momentum",
            }
        ),
    )
    monkeypatch.setattr(chat_server, "_expire_stale_paper_labels", lambda max_age: {"closed_count": 0})
    monkeypatch.setattr(chat_server, "get_persistence_conn", lambda: type("Conn", (), {"__enter__": lambda self: self, "__exit__": lambda self, exc_type, exc, tb: False, "execute": lambda self, *args, **kwargs: type("Cur", (), {"fetchall": lambda self: []})()})())

    status_disabled = {
        "enabled": False,
        "shadow_labeling_enabled": True,
        "symbols": ["BTCUSD"],
        "shadow_label_max_age_minutes": 60,
        "max_open_positions": 3,
        "cooldown_minutes": 30,
        "confidence_threshold": 0.7,
        "volume": 0.02,
    }
    monkeypatch.setattr(chat_server, "_auto_paper_status", lambda: status_disabled)
    monkeypatch.setattr(chat_server, "_shadow_label_cycle_sync", lambda status, summary, open_symbols, open_position_count: summary["skipped"].append({"symbol": "BTCUSD", "reason": "shadow:ok"}) or 1)
    disabled = chat_server._auto_paper_cycle_sync()
    assert disabled["expired_labels"] == {"closed_count": 0}
    assert disabled["skipped"] == [{"symbol": "BTCUSD", "reason": "shadow:ok"}]

    status_enabled = {
        "enabled": True,
        "shadow_labeling_enabled": False,
        "symbols": ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "DOGEUSD", "ADAUSD", "BNBUSD", "AVAXUSD", "LINKUSD"],
        "shadow_label_max_age_minutes": 60,
        "max_open_positions": 99,
        "cooldown_minutes": 30,
        "confidence_threshold": 0.7,
        "volume": 0.02,
    }
    monkeypatch.setattr(chat_server, "_auto_paper_status", lambda: status_enabled)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, *params):
            if "SELECT symbol FROM paper_trades WHERE status = 'OPEN'" in sql:
                return SimpleNamespace(fetchall=lambda: [{"symbol": "ETHUSD"}])
            raise AssertionError(f"unexpected sql: {sql}")

    monkeypatch.setattr(chat_server, "get_persistence_conn", lambda: FakeConn())
    monkeypatch.setattr(chat_server, "_recent_trade_exists", lambda symbol, cooldown_minutes: symbol == "SOLUSD")

    setups = {
        "BTCUSD": RuntimeError("boom"),
        "XAUUSD": {"error": "missing"},
        "DOGEUSD": {"recommendation": "HOLD", "ai_edge": {"signal_confidence": 0.9}, "price": 1},
        "ADAUSD": {"recommendation": "BUY", "ai_edge": {"signal_confidence": 0.2}, "price": 1},
        "BNBUSD": {"recommendation": "BUY", "ai_edge": {"signal_confidence": 0.9}, "price": 1},
        "AVAXUSD": {"recommendation": "BUY", "ai_edge": {"signal_confidence": 0.9}, "price": 1},
        "LINKUSD": {"recommendation": "BUY", "ai_edge": {"signal_confidence": 0.9}, "price": 0},
    }

    def _get_tactics(symbol):
        result = setups.get(symbol, {"recommendation": "BUY", "ai_edge": {"signal_confidence": 0.91}, "price": 101.0, "best_persona": "Momentum"})
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setitem(sys.modules, "intelligence.tools.market_tools", SimpleNamespace(get_trading_tactics=_get_tactics))
    monkeypatch.setattr(chat_server, "_auto_paper_performance_gate", lambda symbol, side, entry_source: {"ok": False, "blockers": ["weak pnl"]} if symbol == "BNBUSD" else {"ok": True, "blockers": []})
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"blockers": ["bad graph"]} if symbol == "AVAXUSD" else {"blockers": []})
    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: {"trade_id": f"{kwargs['symbol']}-1", "entry_price": kwargs["price"], "ml_snapshot_attached": True})
    monkeypatch.setattr(chat_server, "_shadow_label_cycle_sync", lambda status, summary, open_symbols, open_position_count: summary["shadow_opened"].append({"symbol": "SHADOW", "trade_id": "s1"}) or open_position_count + 1)

    enabled = chat_server._auto_paper_cycle_sync()
    skipped = {item["symbol"]: item["reason"] for item in enabled["skipped"]}
    assert skipped["BTCUSD"].startswith("setup_error:")
    assert skipped["ETHUSD"] == "already_open"
    assert skipped["SOLUSD"] == "cooldown_active"
    assert skipped["XAUUSD"] == "no_setup"
    assert skipped["DOGEUSD"] == "recommendation:HOLD"
    assert skipped["ADAUSD"].startswith("confidence:")
    assert skipped["BNBUSD"] == "performance_block"
    assert skipped["AVAXUSD"] == "graph_guard_block"
    assert skipped["LINKUSD"] == "invalid_price"
    assert enabled["opened"] == []
    assert enabled["shadow_opened"] == [{"symbol": "SHADOW", "trade_id": "s1"}]


def test_shadow_label_cycle_sync_paths(monkeypatch):
    summary = {"checked_symbols": [], "skipped": [], "shadow_opened": []}
    status = {"shadow_labeling_enabled": True, "symbols": ["BTCUSD", "ETHUSD", "SOLUSD", "XAUUSD", "DOGEUSD", "ADAUSD", "BNBUSD", "AVAXUSD", "LINKUSD", "MATICUSD"], "max_open_positions": 99, "cooldown_minutes": 30, "shadow_min_probability": 0.35, "volume": 0.02}

    monkeypatch.setattr(chat_server, "INTELLIGENCE_AVAILABLE", False)
    assert chat_server._shadow_label_cycle_sync(status, summary, set(), 0) == 0
    assert summary["skipped"] == [{"symbol": "*", "reason": "shadow:intelligence_unavailable"}]

    summary = {"checked_symbols": [], "skipped": [], "shadow_opened": []}
    monkeypatch.setattr(chat_server, "INTELLIGENCE_AVAILABLE", True)
    monkeypatch.setattr(chat_server, "crypto_intel", SimpleNamespace(get_quick_signals=lambda symbols, timeframe="15m": []))
    monkeypatch.setattr(chat_server, "_recent_trade_exists", lambda symbol, cooldown_minutes: symbol == "SOLUSD")
    monkeypatch.setattr(chat_server, "_quick_signal_symbol", lambda symbol: symbol)
    monkeypatch.setattr(chat_server, "_auto_paper_performance_gate", lambda symbol, side, entry_source: {"ok": False, "blockers": ["weak"]} if symbol == "BNBUSD" else {"ok": True, "blockers": []})
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"blockers": ["bad graph"]} if symbol == "AVAXUSD" else {"blockers": []})

    signal_map = {
        "BTCUSD": "RAISE",
        "ETHUSD": [],
        "XAUUSD": [{"candidate_direction": "HOLD", "ml_win_prob": 0.8}],
        "DOGEUSD": [{"candidate_direction": "BUY", "ml_win_prob": 0.2}],
        "ADAUSD": [{"candidate_direction": "BUY", "ml_win_prob": 0.8, "tradeable": True}],
        "BNBUSD": [{"candidate_direction": "BUY", "ml_win_prob": 0.8}],
        "AVAXUSD": [{"candidate_direction": "BUY", "ml_win_prob": 0.8}],
        "LINKUSD": [{"candidate_direction": "SELL", "ml_win_prob": 0.8, "quality_gate": {"mode": "paper", "blockers": ["x"]}, "price": 10.0}],
        "MATICUSD": [{"candidate_direction": "BUY", "ml_win_prob": 0.9, "quality_gate": {"mode": "paper", "blockers": []}, "price": 1.5}],
    }

    def _signals(symbols, timeframe="15m"):
        symbol = symbols[0]
        result = signal_map[symbol]
        if result == "RAISE":
            raise RuntimeError("sig boom")
        return result

    monkeypatch.setattr(chat_server, "crypto_intel", SimpleNamespace(get_quick_signals=_signals))
    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("open fail")) if kwargs["symbol"] == "LINKUSD" else {"trade_id": "ok-1", "entry_price": kwargs["price"], "ml_snapshot_attached": True})

    count = chat_server._shadow_label_cycle_sync(status, summary, {"ETHUSD"}, 1)
    skipped = {item["symbol"]: item["reason"] for item in summary["skipped"] if item["symbol"] != "*"}
    assert skipped["BTCUSD"].startswith("shadow:signal_error:")
    assert skipped["ETHUSD"] == "shadow:already_open"
    assert skipped["SOLUSD"] == "shadow:cooldown_active"
    assert skipped["XAUUSD"] == "shadow:candidate:HOLD"
    assert skipped["DOGEUSD"].startswith("shadow:probability:")
    assert skipped["ADAUSD"] == "shadow:already_tradeable"
    assert skipped["BNBUSD"] == "shadow:performance_block"
    assert skipped["AVAXUSD"] == "shadow:graph_guard_block"
    assert skipped["LINKUSD"].startswith("shadow:open_error:")
    assert summary["shadow_opened"] == [{"symbol": "MATICUSD", "side": "BUY", "trade_id": "ok-1", "ml_win_prob": 0.9, "price": 1.5, "ml_snapshot_attached": True}]
    assert count == 2


def test_capture_trade_ml_snapshot_paths(monkeypatch):
    class FakeSeries:
        def __init__(self, values):
            self._values = list(values)
            self.iloc = self

        def __getitem__(self, index):
            return self._values[index]

    class FakeFrame:
        def __init__(self, length, atr_value):
            self._length = length
            self._atr = FakeSeries([atr_value] * length)

        def __len__(self):
            return self._length

        def __getitem__(self, key):
            if key == "atr_14":
                return self._atr
            raise KeyError(key)

    short_df = FakeFrame(100, 5.0)
    full_df = FakeFrame(260, 10.0)
    zero_atr_df = FakeFrame(260, 0.0)
    current = {"df": short_df}

    monkeypatch.setitem(
        sys.modules,
        "intelligence.technical_engine",
        SimpleNamespace(
            get_kline_data=lambda *args, **kwargs: current["df"],
            compute_indicators=lambda df: df,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.feature_extractor",
        SimpleNamespace(extract_features=lambda df, idx, side, symbol, asset_class: {"side": side, "symbol": symbol, "asset_class": asset_class}),
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.signal_model",
        SimpleNamespace(predict_win_probability=lambda features: {"win_pct": 68.0, "win_probability": 0.73}),
    )

    assert chat_server._capture_trade_ml_snapshot("BTCUSD", "BUY", 100.0) is None

    current["df"] = zero_atr_df
    assert chat_server._capture_trade_ml_snapshot("ETHUSD", "SELL", 200.0) is None

    current["df"] = full_df
    buy_snapshot = chat_server._capture_trade_ml_snapshot("BTCUSD", "BUY", 100.0)
    assert buy_snapshot["sl"] == 85.0
    assert buy_snapshot["tp"] == 130.0
    assert buy_snapshot["ml_score"] == 68.0
    assert buy_snapshot["win_probability"] == 0.73
    assert buy_snapshot["timeframe"] == "15m"
    assert buy_snapshot["asset_class"] == "CRYPTO"
    assert buy_snapshot["features"]["symbol"] == "BTCUSD"
    assert buy_snapshot["features"]["timeframe"] == "15m"

    sell_snapshot = chat_server._capture_trade_ml_snapshot("XAUUSD", "SELL", 100.0)
    assert sell_snapshot["sl"] == 115.0
    assert sell_snapshot["tp"] == 70.0
    assert sell_snapshot["timeframe"] == "1h"
    assert sell_snapshot["asset_class"] == "MACRO"

    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", SimpleNamespace(predict_win_probability=lambda features: (_ for _ in ()).throw(RuntimeError("model down"))))
    assert chat_server._capture_trade_ml_snapshot("BTCUSD", "BUY", 100.0) is None


def test_paper_trade_api_helpers_and_endpoints(tmp_path, monkeypatch):
    db_path = tmp_path / "paperapi.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    monkeypatch.setattr(chat_server, "require_request_api_key", lambda request: None)

    snapshot = {
        "summary": {"total": 3},
        "open_trades": [{"id": "o1"}] * 10,
        "closed_trades": [{"id": "c1"}] * 10,
    }
    monkeypatch.setattr(chat_server, "_paper_trade_snapshot", lambda: snapshot)
    assert asyncio.run(chat_server.get_paper_trades(SimpleNamespace())) == snapshot

    summary_payload = asyncio.run(chat_server.get_paper_trades_summary(SimpleNamespace()))
    assert summary_payload["summary"] == {"total": 3}
    assert len(summary_payload["recent_open_trades"]) == 8
    assert len(summary_payload["recent_closed_trades"]) == 8

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.performance_feedback",
        SimpleNamespace(get_feedback_snapshot=lambda force_refresh=True: {"strategy": {"ok": 1}, "symbol": {"BTCUSD": 2}, "symbol_side": {"BTCUSD:BUY": 3}, "recommendations": ["tighten"]}),
    )
    scorecard = asyncio.run(chat_server.get_paper_trades_scorecard(SimpleNamespace()))
    assert scorecard["strategy"] == {"ok": 1}
    assert scorecard["recommendations"] == ["tighten"]

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.paper_analytics",
        SimpleNamespace(build_side_scorecard=lambda limit=50: {"available": True, "limit": limit}),
    )
    side_scorecard = asyncio.run(chat_server.get_paper_trades_side_scorecard(SimpleNamespace(), limit=12))
    assert side_scorecard == {"available": True, "limit": 12}

    opened_payload = {"status": "opened", "trade_id": "pt-1"}
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action: {"status": "ok", "action": action})
    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: dict(opened_payload))

    attach_calls = []
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.outcome_tracker",
        SimpleNamespace(attach_sl_tp_features=lambda *args: attach_calls.append(args)),
    )
    create_payload = chat_server.PaperTradeCreateRequest(
        symbol="BTCUSD",
        side="BUY",
        volume=0.5,
        price=65000.0,
        entry_source="manual_api",
        entry_reason="api open",
        stop_loss=64000.0,
        take_profit=68000.0,
        features={"rsi": 55},
        ml_score=0.88,
        signal_grade="A",
        macro_bias="bullish",
    )
    created = asyncio.run(chat_server.create_paper_trade(create_payload, SimpleNamespace()))
    assert created["trade_id"] == "pt-1"
    assert created["custom_levels_attached"] is True
    assert attach_calls[0][0] == "pt-1"
    assert attach_calls[0][1] == 64000.0
    assert attach_calls[0][2] == 68000.0

    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.outcome_tracker",
        SimpleNamespace(attach_sl_tp_features=lambda *args: (_ for _ in ()).throw(RuntimeError("attach failed"))),
    )
    failed_attach = asyncio.run(chat_server.create_paper_trade(create_payload, SimpleNamespace()))
    assert failed_attach["custom_levels_attached"] is False
    assert "attach failed" in failed_attach["custom_levels_error"]

    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: {"status": "opened", "trade_id": "pt-2"})
    plain_payload = chat_server.PaperTradeCreateRequest(symbol="ETHUSD", side="SELL", volume=1.0)
    plain_created = asyncio.run(chat_server.create_paper_trade(plain_payload, SimpleNamespace()))
    assert "custom_levels_attached" not in plain_created

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                status, opened_at, ml_score, entry_source, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?)
            """,
            ("close-1", "BTCUSD", "BUY", 2.0, 2.0, 100.0, 105.0, "2026-01-01T00:00:00+00:00", 0.5, "manual", "seed"),
        )
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                status, opened_at, ml_score, entry_source, entry_reason, pnl_usd
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?, ?, ?, ?, ?)
            """,
            ("closed-1", "ETHUSD", "SELL", 1.0, 1.0, 200.0, 180.0, "2026-01-01T00:00:00+00:00", 0.4, "manual", "seed", 20.0),
        )
        conn.commit()

    audits = []
    monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: audits.append((event_type, detail)))
    ensured = []
    monkeypatch.setattr(chat_server, "_ensure_trade_review_snapshots", lambda: ensured.append("ok"))
    monkeypatch.setattr(chat_server, "_maybe_trigger_auto_retrain", lambda reason: {"status": "queued", "reason": reason})
    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 110.0 if symbol == "BTCUSD" else 0.0)

    closed = asyncio.run(
        chat_server.close_paper_trade(
            "close-1",
            chat_server.PaperTradeCloseRequest(),
            SimpleNamespace(),
        )
    )
    assert closed["status"] == "closed"
    assert closed["exit_price"] == 110.0
    assert closed["pnl_usd"] == 20.0
    assert closed["outcome"] == "WIN"
    assert closed["auto_retrain"] == {"status": "queued", "reason": "manual_close"}
    assert ensured == ["ok"]
    assert audits[0][0] == "PAPER_TRADE"

    already_closed = asyncio.run(
        chat_server.close_paper_trade(
            "closed-1",
            chat_server.PaperTradeCloseRequest(),
            SimpleNamespace(),
        )
    )
    assert already_closed["status"] == "already_closed"
    assert already_closed["trade_id"] == "closed-1"

    try:
        asyncio.run(chat_server.close_paper_trade("missing", chat_server.PaperTradeCloseRequest(), SimpleNamespace()))
        raise AssertionError("expected 404 for missing paper trade")
    except chat_server.HTTPException as exc:
        assert exc.status_code == 404

    reset_result = asyncio.run(chat_server.reset_paper_trades(SimpleNamespace()))
    assert reset_result == {"status": "cleared"}
    with chat_server.get_persistence_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM paper_trades").fetchone()
    assert row["c"] == 0


def test_auto_paper_config_and_run_once_endpoints(monkeypatch):
    monkeypatch.setattr(chat_server, "require_request_api_key", lambda request: None)
    original_state = dict(chat_server._auto_paper_state)
    try:
        payload = chat_server.AutoPaperConfigUpdate(
            enabled=True,
            shadow_labeling_enabled=False,
            confidence_threshold=0.99,
            shadow_min_probability=0.1,
            shadow_label_max_age_minutes=10,
            volume=0.0,
            cooldown_minutes=1,
            max_open_positions=0,
            scan_interval_seconds=1,
            symbols=[" btcusd ", "", "ethusd"],
        )
        audits = []
        monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: audits.append((event_type, detail)))
        updated = asyncio.run(chat_server.update_auto_paper_status(payload, SimpleNamespace()))
        assert updated["enabled"] is True
        assert updated["shadow_labeling_enabled"] is False
        assert updated["confidence_threshold"] == 0.95
        assert updated["shadow_min_probability"] == 0.3
        assert updated["shadow_label_max_age_minutes"] == 30
        assert updated["volume"] == 0.001
        assert updated["cooldown_minutes"] == 5
        assert updated["max_open_positions"] == 1
        assert updated["scan_interval_seconds"] == 10
        assert updated["symbols"] == ["BTCUSD", "ETHUSD"]
        assert audits and audits[0][0] == "AUTO_PAPER"

        monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: (_ for _ in ()).throw(RuntimeError("audit down")))
        still_updated = asyncio.run(chat_server.update_auto_paper_status(chat_server.AutoPaperConfigUpdate(symbols=[]), SimpleNamespace()))
        assert still_updated["symbols"] == list(chat_server.AUTO_PAPER_DEFAULTS["symbols"])

        monkeypatch.setattr(chat_server, "_auto_paper_cycle_sync", lambda: {"opened": [{"symbol": "BTCUSD"}]})
        completed = asyncio.run(chat_server.run_auto_paper_once(SimpleNamespace()))
        assert completed["status"] == "completed"
        assert completed["summary"] == {"opened": [{"symbol": "BTCUSD"}]}
        assert completed["config"]["last_summary"] == {"opened": [{"symbol": "BTCUSD"}]}
        assert completed["config"]["last_error"] is None

        monkeypatch.setattr(chat_server, "_auto_paper_cycle_sync", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
        deferred = asyncio.run(chat_server.run_auto_paper_once(SimpleNamespace()))
        assert deferred["status"] == "deferred"
        assert "SQLite is busy" in deferred["message"]
        assert "locked" in deferred["error"]
        assert deferred["config"]["last_error"] == "database is locked"
    finally:
        chat_server._auto_paper_state.clear()
        chat_server._auto_paper_state.update(original_state)


def test_chat_server_decision_and_rag_endpoint_wrappers(monkeypatch):
    monkeypatch.setattr(chat_server, "require_request_api_key", lambda request: None)
    monkeypatch.setattr(chat_server, "_build_best_setup_payload", lambda use_cache=True: {"items": [1], "model_trust": None, "used_cache": use_cache})
    monkeypatch.setattr(chat_server, "_ml_model_trust_snapshot", lambda: {"ready": True})
    chat_server._best_setup_state["last_run_at"] = "2026-01-01T00:00:00+00:00"
    chat_server._best_setup_state["last_error"] = None

    best_setup = asyncio.run(chat_server.get_best_setup(SimpleNamespace(), force_refresh=False))
    refreshed = asyncio.run(chat_server.get_best_setup(SimpleNamespace(), force_refresh=True))
    assert best_setup["used_cache"] is True
    assert refreshed["used_cache"] is False
    assert best_setup["scanner"]["last_run_at"] == "2026-01-01T00:00:00+00:00"
    assert best_setup["model_trust"] == {"ready": True}

    monkeypatch.setattr(chat_server, "_best_setup_metrics", lambda limit, evaluate: {"limit": limit, "evaluate": evaluate})
    metrics = asyncio.run(chat_server.get_best_setup_metrics(SimpleNamespace(), limit=5, evaluate=True))
    assert metrics == {"limit": 50, "evaluate": True}

    monkeypatch.setattr(chat_server, "_daily_risk_guard", lambda chat_id=None: {"status": "ok", "chat_id": chat_id})
    assert asyncio.run(chat_server.get_daily_risk_guard(SimpleNamespace(), chat_id="42")) == {"status": "ok", "chat_id": "42"}

    monkeypatch.setattr(chat_server, "_sync_trade_memory_to_rag", lambda force=False: {"status": "OK", "force": force})
    synced = asyncio.run(chat_server.sync_rag_trade_memory(SimpleNamespace(), force=True))
    assert synced == {"status": "OK", "force": True}

    monkeypatch.setattr(chat_server, "_sync_trade_memory_to_rag", lambda force=False: {"status": "ERROR", "reason": "boom"})
    try:
        asyncio.run(chat_server.sync_rag_trade_memory(SimpleNamespace(), force=False))
        raise AssertionError("expected rag sync HTTPException")
    except chat_server.HTTPException as exc:
        assert exc.status_code == 500

    monkeypatch.setattr(chat_server, "_pre_graph_rag_readiness", lambda: {"blockers": ["db"], "status": "warn"})
    monkeypatch.setattr(chat_server, "_build_trade_knowledge_graph", lambda limit: {"status": "built", "limit": limit})
    built_warn = asyncio.run(chat_server.build_rag_trade_graph(SimpleNamespace(), limit=12))
    assert built_warn["status"] == "BUILT_WITH_WARNINGS"
    assert built_warn["graph"] == {"status": "built", "limit": 12}

    monkeypatch.setattr(chat_server, "_pre_graph_rag_readiness", lambda: {"blockers": [], "status": "ok"})
    built_ok = asyncio.run(chat_server.build_rag_trade_graph(SimpleNamespace(), limit=7))
    assert built_ok == {"status": "built", "limit": 7}

    monkeypatch.setattr(chat_server, "_trade_graph_status", lambda: {"status": "OK"})
    monkeypatch.setattr(chat_server, "_query_trade_graph", lambda symbol=None, side=None, limit=25: {"symbol": symbol, "side": side, "limit": limit})
    monkeypatch.setattr(chat_server, "_trade_graph_guard", lambda symbol, side: {"symbol": symbol, "side": side, "blockers": []})
    monkeypatch.setattr(chat_server, "_signal_snapshot_metrics", lambda limit=1000, evaluate=False: {"limit": limit, "evaluate": evaluate})
    monkeypatch.setattr(chat_server, "_current_market_regime", lambda: "RISK_ON")
    monkeypatch.setattr(chat_server, "resolve_trade_symbol", lambda symbol: {"input": symbol, "normalized": symbol.upper()})
    monkeypatch.setattr(chat_server, "_best_alternative_candidates", lambda chat_id=None: {"chat_id": chat_id, "items": ["ETHUSD"]})
    monkeypatch.setattr(chat_server, "_open_best_paper_evidence", lambda chat_id=None, volume=None: {"chat_id": chat_id, "volume": volume, "status": "opened"})

    assert asyncio.run(chat_server.get_rag_trade_graph_status(SimpleNamespace())) == {"status": "OK"}
    assert asyncio.run(chat_server.query_rag_trade_graph(SimpleNamespace(), symbol="BTCUSD", side="BUY", limit=8)) == {"symbol": "BTCUSD", "side": "BUY", "limit": 8}
    assert asyncio.run(chat_server.get_rag_trade_graph_guard(SimpleNamespace(), symbol="ETHUSD", side="SELL")) == {"symbol": "ETHUSD", "side": "SELL", "blockers": []}
    assert asyncio.run(chat_server.get_signal_memory(SimpleNamespace(), limit=55, evaluate=True)) == {"limit": 55, "evaluate": True}

    why = asyncio.run(chat_server.get_decision_why(SimpleNamespace(), symbol="btcusd", side="BUY"))
    assert why["symbol_resolution"]["normalized"] == "BTCUSD"
    assert why["graph_guard"]["blockers"] == []
    assert why["market_regime"] == "RISK_ON"

    best_alt = asyncio.run(chat_server.get_decision_best_alternative(SimpleNamespace(), chat_id="99"))
    assert best_alt == {"chat_id": "99", "items": ["ETHUSD"]}

    opened = asyncio.run(chat_server.post_decision_open_best_paper(SimpleNamespace(), chat_id="99", volume=0.3))
    assert opened == {"chat_id": "99", "volume": 0.3, "status": "opened"}

    auto_status = asyncio.run(chat_server.get_auto_paper_status(SimpleNamespace()))
    assert auto_status["symbols"]


def test_chat_server_telegram_alert_and_confirmation_helpers(tmp_path, monkeypatch):
    db_path = tmp_path / "telegram_helpers.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    parse_calls = []
    monkeypatch.setattr(
        chat_server,
        "_helper_telegram_parse_alert_request",
        lambda text, **kwargs: parse_calls.append((text, kwargs)) or {"symbol": "BTCUSD", "condition": "above", "price": 100.0},
    )
    parsed = chat_server._telegram_parse_alert_request("/alert btc above 100")
    assert parsed == {"symbol": "BTCUSD", "condition": "above", "price": 100.0}
    assert parse_calls[0][1]["trigger_terms"]

    cache_deletes = []
    audits = []
    monkeypatch.setattr(chat_server, "_cache_delete", lambda key: cache_deletes.append(key))
    monkeypatch.setattr(chat_server, "_append_audit_event", lambda event_type, detail: audits.append((event_type, detail)))
    created = chat_server._telegram_create_price_alert(
        "99",
        {"symbol": "btcusd", "condition": "above", "price": 123.45, "message": "ping"},
    )
    assert created["symbol"] == "BTCUSD"
    assert created["condition"] == "above"
    assert cache_deletes == ["alerts_payload_v1"]
    assert audits[0][0] == "TELEGRAM_ALERT"

    with chat_server.get_persistence_conn() as conn:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (created["id"],)).fetchone()
    assert row["user_id"] == "telegram:99"
    assert row["entry_source"] == "telegram_bot"

    try:
        chat_server._telegram_create_price_alert("99", {"symbol": "", "condition": "above", "price": 0})
        raise AssertionError("expected invalid alert request to fail")
    except ValueError:
        pass

    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: {"preferred_symbols": ["ETHUSD"]})
    monkeypatch.setattr(
        chat_server,
        "_build_best_setup_payload",
        lambda universe=None, use_cache=True: {"candidates": [{"symbol": "ETHUSD"}], "meta": "x"},
    )
    monkeypatch.setattr(
        chat_server,
        "_helper_build_best_entry_alert_request",
        lambda top, payload, num_fn=None: {"symbol": top["symbol"], "condition": "above", "price": 200.0, "metadata": {"kind": "entry"}},
    )
    monkeypatch.setattr(
        chat_server,
        "_helper_build_best_confirmation_alert_request",
        lambda top, payload, num_fn=None: {"symbol": top["symbol"], "condition": "below", "price": 180.0, "metadata": {"kind": "confirm"}},
    )

    best_entry = chat_server._telegram_create_best_entry_alert("42")
    best_confirm = chat_server._telegram_create_best_confirmation_alert("42")
    assert best_entry["kind"] == "entry"
    assert best_confirm["kind"] == "confirm"

    monkeypatch.setattr(chat_server, "_build_best_setup_payload", lambda universe=None, use_cache=True: {"candidates": []})
    try:
        chat_server._telegram_create_best_entry_alert("42")
        raise AssertionError("expected no best setup error")
    except ValueError:
        pass
    try:
        chat_server._telegram_create_best_confirmation_alert("42")
        raise AssertionError("expected no best setup confirmation error")
    except ValueError:
        pass

    monkeypatch.setattr(chat_server, "_helper_telegram_trade_keyboard", lambda confirmation_id: {"id": confirmation_id, "type": "trade"})
    monkeypatch.setattr(chat_server, "_helper_telegram_blocked_trade_keyboard", lambda confirmation_id: {"id": confirmation_id, "type": "blocked"})
    monkeypatch.setattr(chat_server, "_helper_telegram_extract_blockers", lambda result: [{"source": "gate", "message": result.get("reason", "")}])
    monkeypatch.setattr(chat_server, "_helper_telegram_format_blocked_trade", lambda confirmation_id, result, gate: f"{confirmation_id}:{result.get('reason')}:{bool(gate)}")
    monkeypatch.setattr(chat_server, "_helper_telegram_format_blocked_detail", lambda confirmation_id, request, result, gate: f"{confirmation_id}:{request.get('symbol')}:{result.get('reason')}:{bool(gate)}")
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.trading_quality_gate",
        SimpleNamespace(get_trading_quality_gate=lambda force_refresh=True: {"mode": "observe_only"}),
    )

    request = {"symbol": "BTCUSD", "side": "buy", "volume": 0.5, "sl": 95.0, "tp": 120.0, "price": 100.0}
    draft = chat_server._telegram_create_trade_confirmation("chat-1", request)
    assert draft["symbol"] == "BTCUSD"
    assert draft["side"] == "buy"
    assert chat_server._telegram_trade_keyboard(draft["id"]) == {"id": draft["id"], "type": "trade"}
    assert chat_server._telegram_blocked_trade_keyboard(draft["id"]) == {"id": draft["id"], "type": "blocked"}
    assert chat_server._telegram_extract_blockers({"reason": "blocked"}) == [{"source": "gate", "message": "blocked"}]

    row = chat_server._telegram_get_trade_confirmation(draft["id"], "chat-1")
    assert row["symbol"] == "BTCUSD"
    chat_server._telegram_update_trade_confirmation(draft["id"], "BLOCKED", {"reason": "blocked"})
    blocked_text = chat_server._telegram_format_blocked_trade(draft["id"], {"reason": "blocked"})
    blocked_detail = chat_server._telegram_format_blocked_detail(draft["id"])
    assert blocked_text.startswith(f"{draft['id']}:blocked")
    assert blocked_detail.startswith(f"{draft['id']}:BTCUSD:blocked")
    assert chat_server._telegram_get_trade_confirmation("missing", "chat-1") is None
    assert chat_server._telegram_format_blocked_detail("missing") == "Blocked detail not found."

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                status, opened_at, entry_source, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            """,
            ("paper-1", "BTCUSD", "BUY", 1.0, 1.0, 100.0, 101.0, "2026-01-01T00:00:00+00:00", "telegram_blocked_live_fallback", f"fallback for {draft['id']}"),
        )
        conn.commit()

    existing = chat_server._telegram_existing_paper_for_confirmation(draft["id"])
    assert existing["id"] == "paper-1"


def test_chat_server_telegram_entry_price_resolution(monkeypatch):
    assert chat_server._telegram_resolve_paper_entry_price("BTCUSD", "BUY", fallback_price=321.0) == 321.0

    monkeypatch.setitem(
        sys.modules,
        "intelligence.mt5_connector",
        SimpleNamespace(resolve_broker_symbol=lambda symbol: {"quote": {"bid": 99.0, "ask": 101.0, "last": 100.5}}),
    )
    assert chat_server._telegram_resolve_paper_entry_price("BTCUSD", "BUY") == 101.0
    assert chat_server._telegram_resolve_paper_entry_price("BTCUSD", "SELL") == 99.0
    assert chat_server._telegram_resolve_paper_entry_price("BTCUSD", "HOLD") == 100.0

    monkeypatch.setitem(
        sys.modules,
        "intelligence.mt5_connector",
        SimpleNamespace(resolve_broker_symbol=lambda symbol: {"quote": {"bid": 0.0, "ask": 0.0, "last": 88.0}}),
    )
    assert chat_server._telegram_resolve_paper_entry_price("ETHUSD", "BUY") == 88.0

    monkeypatch.setitem(
        sys.modules,
        "intelligence.mt5_connector",
        SimpleNamespace(resolve_broker_symbol=lambda symbol: (_ for _ in ()).throw(RuntimeError("mt5 down"))),
    )
    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 77.7)
    assert chat_server._telegram_resolve_paper_entry_price("XAUUSD", "BUY") == 77.7

    monkeypatch.setattr(chat_server, "_get_live_price", lambda symbol: 0.0)
    assert chat_server._telegram_resolve_paper_entry_price("XAUUSD", "BUY") == 0.0


def test_chat_server_telegram_async_confirmation_flows(tmp_path, monkeypatch):
    db_path = tmp_path / "telegram_async.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    sent = []

    async def _send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    monkeypatch.setattr(chat_server.notifier, "send_telegram_message", _send)
    monkeypatch.setattr(chat_server, "_telegram_keyboard", lambda: {"k": "main"})
    monkeypatch.setattr(chat_server, "_telegram_paper_keyboard", lambda: {"k": "paper"})
    monkeypatch.setattr(chat_server, "_telegram_blocked_trade_keyboard", lambda confirmation_id: {"blocked": confirmation_id})
    monkeypatch.setattr(chat_server, "_telegram_format_blocked_trade", lambda confirmation_id, result: f"blocked:{confirmation_id}:{result.get('status')}")
    monkeypatch.setattr(chat_server, "_telegram_format_paper", lambda: "paper summary")

    request = {"symbol": "BTCUSD", "side": "BUY", "volume": 0.5, "sl": 95.0, "tp": 120.0, "price": 100.0}
    draft = chat_server._telegram_create_trade_confirmation("chat-1", request)

    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", "missing"))
    assert sent[-1][1] == "Trade confirmation not found."

    def _guard_block(action, chat_id=None):
        raise chat_server.HTTPException(
            status_code=409,
            detail={"guard": {"status": "blocked", "blockers": ["daily_loss"]}, "message": "guard blocked"},
        )

    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", _guard_block)
    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", draft["id"]))
    assert "Paper fallback blocked by daily risk guard." in sent[-1][1]

    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action, chat_id=None: {"status": "ok"})
    monkeypatch.setattr(chat_server, "_telegram_existing_paper_for_confirmation", lambda confirmation_id: {"id": "p1", "symbol": "BTCUSD", "side": "BUY", "status": "OPEN", "entry_price": 101.0})
    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", draft["id"]))
    assert "Paper trade already exists" in sent[-1][1]

    monkeypatch.setattr(chat_server, "_telegram_existing_paper_for_confirmation", lambda confirmation_id: None)
    monkeypatch.setattr(chat_server, "_telegram_resolve_paper_entry_price", lambda symbol, side, fallback_price=None: 0.0)
    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", draft["id"]))
    assert "unable to resolve MT5 or market entry price" in sent[-1][1]

    audits = []
    monkeypatch.setattr(chat_server, "_telegram_audit", lambda *args, **kwargs: audits.append((args, kwargs)))
    monkeypatch.setattr(chat_server, "_telegram_resolve_paper_entry_price", lambda symbol, side, fallback_price=None: 111.1)
    monkeypatch.setattr(
        chat_server,
        "_open_paper_trade_internal",
        lambda **kwargs: {"trade_id": "paper-123", "entry_price": kwargs["price"]},
    )
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.outcome_tracker",
        SimpleNamespace(attach_sl_tp_features=lambda *args: None),
    )
    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", draft["id"]))
    assert "Opened paper trade instead." in sent[-1][1]
    assert audits

    monkeypatch.setattr(chat_server, "_open_paper_trade_internal", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("open boom")))
    asyncio.run(chat_server._telegram_open_paper_from_confirmation("chat-1", draft["id"]))
    assert "Paper fallback failed: open boom" in sent[-1][1]

    sent.clear()
    asyncio.run(chat_server._telegram_confirm_trade("chat-1", "missing"))
    assert sent[-1][1] == "Trade confirmation not found."

    expired = chat_server._telegram_create_trade_confirmation("chat-1", request)
    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            "UPDATE telegram_trade_confirmations SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", expired["id"]),
        )
        conn.commit()
    asyncio.run(chat_server._telegram_confirm_trade("chat-1", expired["id"]))
    assert "Trade confirmation expired." in sent[-1][1]

    blocked = chat_server._telegram_create_trade_confirmation("chat-1", request)
    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", _guard_block)
    asyncio.run(chat_server._telegram_confirm_trade("chat-1", blocked["id"]))
    assert "Live order blocked by daily risk guard." in sent[-1][1]

    monkeypatch.setattr(chat_server, "_assert_daily_risk_guard_allows", lambda action, chat_id=None: {"status": "ok"})
    monkeypatch.setitem(
        sys.modules,
        "intelligence.tools.market_tools",
        SimpleNamespace(execute_mt5_trade=lambda **kwargs: {"status": "SUCCESS", "ticket": 7}),
    )
    executed = chat_server._telegram_create_trade_confirmation("chat-1", request)
    asyncio.run(chat_server._telegram_confirm_trade("chat-1", executed["id"]))
    assert "Live order executed." in sent[-1][1]

    errored = chat_server._telegram_create_trade_confirmation("chat-1", request)
    monkeypatch.setitem(
        sys.modules,
        "intelligence.tools.market_tools",
        SimpleNamespace(execute_mt5_trade=lambda **kwargs: {"status": "ERROR", "message": "blocked"}),
    )
    asyncio.run(chat_server._telegram_confirm_trade("chat-1", errored["id"]))
    assert sent[-1][1].startswith(f"blocked:{errored['id']}:ERROR")

    sent.clear()
    asyncio.run(chat_server._telegram_cancel_trade("chat-1", "missing"))
    assert sent[-1][1] == "Trade confirmation not found."

    cancelled = chat_server._telegram_create_trade_confirmation("chat-1", request)
    cancel_audits = []
    monkeypatch.setattr(chat_server, "_telegram_audit", lambda *args, **kwargs: cancel_audits.append((args, kwargs)))
    asyncio.run(chat_server._telegram_cancel_trade("chat-1", cancelled["id"]))
    assert f"Cancelled trade confirmation {cancelled['id']}." in sent[-1][1]
    assert cancel_audits
    asyncio.run(chat_server._telegram_cancel_trade("chat-1", cancelled["id"]))
    assert "already CANCELLED" in sent[-1][1]

    monkeypatch.setattr(chat_server, "_auto_paper_cycle_sync", lambda: {"opened": [1, 2], "shadow_opened": [1], "expired_labels": {"closed_count": 3}, "skipped": [1, 2, 3]})
    asyncio.run(chat_server._telegram_run_paper_scan("chat-1"))
    assert "Paper scan completed" in sent[-1][1]
    assert "Opened auto trades: 2" in sent[-1][1]

    monkeypatch.setattr(chat_server, "_auto_paper_cycle_sync", lambda: (_ for _ in ()).throw(RuntimeError("scan fail")))
    asyncio.run(chat_server._telegram_run_paper_scan("chat-1"))
    assert "Paper scan failed: scan fail" in sent[-1][1]


def test_chat_server_telegram_reply_routing(monkeypatch):
    sent = []

    async def _send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    monkeypatch.setattr(chat_server.notifier, "send_telegram_message", _send)
    monkeypatch.setattr(chat_server, "_telegram_keyboard", lambda: {"k": "main"})
    monkeypatch.setattr(chat_server, "_telegram_paper_keyboard", lambda: {"k": "paper"})
    monkeypatch.setattr(chat_server, "_telegram_help_text", lambda: "help text")
    monkeypatch.setattr(chat_server, "_telegram_extract_profile_patch", lambda raw, user=None: {"language": "en"} if raw == "profile patch" else {})
    saved_profiles = []
    monkeypatch.setattr(chat_server, "_telegram_save_profile", lambda chat_id, patch: saved_profiles.append((chat_id, patch)) or {"chat_id": chat_id, **patch})
    monkeypatch.setattr(chat_server, "_telegram_get_profile", lambda chat_id: {"chat_id": chat_id, "preferred_symbols": ["BTCUSD"]})
    monkeypatch.setattr(chat_server, "_telegram_profile_text", lambda profile: f"profile:{profile['chat_id']}")
    monkeypatch.setattr(chat_server, "_telegram_symbols_from_text", lambda raw: ["BTCUSD", "ETHUSD"])
    monkeypatch.setattr(chat_server, "build_system_readiness", lambda: {"ready": True})
    monkeypatch.setattr(chat_server, "_telegram_format_readiness", lambda readiness: f"readiness:{readiness['ready']}")
    monkeypatch.setattr(chat_server, "_telegram_format_best_setup", lambda chat_id=None: f"best:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_best_feedback_keyboard", lambda chat_id=None: {"best": chat_id})
    monkeypatch.setattr(chat_server, "_telegram_format_best_alternative", lambda chat_id=None: f"alt:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_open_best_paper_text", lambda chat_id=None: f"paperbest:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_no_trade_reason", lambda chat_id=None: f"notrade:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_why_setup", lambda raw, chat_id=None: f"why:{raw}:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_best_metrics", lambda: "metrics")
    monkeypatch.setattr(chat_server, "_telegram_format_risk_guard", lambda chat_id=None: f"risk:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_mt5", lambda: "mt5")
    monkeypatch.setattr(chat_server, "_telegram_format_paper", lambda: "paper")
    monkeypatch.setattr(chat_server, "_telegram_format_feedback", lambda chat_id=None: f"feedback:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_rag", lambda: "rag")
    monkeypatch.setattr(chat_server, "_telegram_format_trade_graph", lambda raw="": f"graph:{raw}")
    monkeypatch.setattr(chat_server, "_telegram_format_alerts", lambda: "alerts")
    monkeypatch.setattr(chat_server, "_telegram_format_audit", lambda chat_id: f"audit:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_parse_alert_request", lambda raw: None if "badalert" in raw else {"symbol": "BTCUSD", "condition": "above", "price": 100.0})
    monkeypatch.setattr(chat_server, "_telegram_create_price_alert", lambda chat_id, req: {"id": 7, **req})
    alert_audits = []
    monkeypatch.setattr(chat_server, "_telegram_audit", lambda *args, **kwargs: alert_audits.append((args, kwargs)))
    trade_calls = []

    async def _trade(chat_id, raw):
        trade_calls.append((chat_id, raw))

    monkeypatch.setattr(chat_server, "_telegram_execute_trade_command", _trade)
    scan_calls = []

    async def _scan(chat_id):
        scan_calls.append(chat_id)

    monkeypatch.setattr(chat_server, "_telegram_run_paper_scan", _scan)

    monkeypatch.setattr(chat_server, "INTELLIGENCE_AVAILABLE", True)
    monkeypatch.setattr(chat_server, "crypto_intel", SimpleNamespace(get_quick_signals=lambda symbols, timeframe="15m": [{"symbol": "BTCUSDT", "candidate_direction": "BUY", "ml_win_prob": 0.8, "tradeable": True}]))
    monkeypatch.setitem(
        sys.modules,
        "intelligence.tools.market_tools",
        SimpleNamespace(get_trading_tactics=lambda symbol: {"symbol": symbol, "entry": 100.0}),
    )
    record_calls = []
    monkeypatch.setattr(chat_server, "_record_signal_snapshot", lambda setup, source, timeframe: record_calls.append((setup, source, timeframe)))
    monkeypatch.setattr(chat_server, "_telegram_format_signal", lambda symbol, setup: f"signal:{symbol}:{setup['symbol']}")

    async def _finance(raw, chat_id):
        return f"finance:{raw}:{chat_id}"

    monkeypatch.setattr(chat_server, "_telegram_finance_agent_answer", _finance)

    asyncio.run(chat_server._telegram_reply_for_text("42", "/help"))
    assert sent[-1][1] == "help text"

    asyncio.run(chat_server._telegram_reply_for_text("42", "/profile"))
    assert sent[-1][1] == "profile:42"

    asyncio.run(chat_server._telegram_reply_for_text("42", "/watch btc eth"))
    assert "watchlist" in sent[-1][1]

    asyncio.run(chat_server._telegram_reply_for_text("42", "/setlot"))
    assert "ใช้แบบนี้" in sent[-1][1]
    asyncio.run(chat_server._telegram_reply_for_text("42", "/setlot x"))
    assert "lot ต้องเป็นตัวเลข" in sent[-1][1]
    asyncio.run(chat_server._telegram_reply_for_text("42", "/setlot 0.01"))
    assert "lot ปกติ" in sent[-1][1]

    asyncio.run(chat_server._telegram_reply_for_text("42", "/setrisk"))
    assert "ใช้แบบนี้" in sent[-1][1]
    asyncio.run(chat_server._telegram_reply_for_text("42", "/setrisk x"))
    assert "risk ต้องเป็นตัวเลข" in sent[-1][1]
    asyncio.run(chat_server._telegram_reply_for_text("42", "/setrisk 2"))
    assert "risk ต่อไม้" in sent[-1][1]

    asyncio.run(chat_server._telegram_reply_for_text("42", "/status"))
    assert sent[-1][1] == "readiness:True"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/best"))
    assert sent[-1][1] == "best:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/bestalt"))
    assert sent[-1][1] == "alt:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/openbestpaper"))
    assert sent[-1][1] == "paperbest:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/whybest"))
    assert sent[-1][1] == "notrade:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/why BTC"))
    assert sent[-1][1] == "why:/why BTC:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/beststats"))
    assert sent[-1][1] == "metrics"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/riskguard"))
    assert sent[-1][1] == "risk:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/mt5"))
    assert sent[-1][1] == "mt5"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/paper"))
    assert sent[-1][1] == "paper"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/feedback"))
    assert sent[-1][1] == "feedback:42"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/rag"))
    assert sent[-1][1] == "rag"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/graph btc"))
    assert sent[-1][1] == "graph:/graph btc"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/alerts"))
    assert sent[-1][1] == "alerts"
    asyncio.run(chat_server._telegram_reply_for_text("42", "/audit"))
    assert sent[-1][1] == "audit:42"

    asyncio.run(chat_server._telegram_reply_for_text("42", "/alert badalert"))
    assert "สร้าง alert ไม่สำเร็จ" in sent[-1][1]
    asyncio.run(chat_server._telegram_reply_for_text("42", "/alert btc above 100"))
    assert "สร้าง price alert แล้วครับ" in sent[-1][1]
    assert alert_audits

    asyncio.run(chat_server._telegram_reply_for_text("42", "/trade BTCUSD BUY 1 95 120"))
    assert trade_calls[-1] == ("42", "/trade BTCUSD BUY 1 95 120")
    asyncio.run(chat_server._telegram_reply_for_text("42", "/paperscan"))
    assert scan_calls[-1] == "42"

    asyncio.run(chat_server._telegram_reply_for_text("42", "/signals"))
    assert "Latest AI signals" in sent[-1][1]
    monkeypatch.setattr(chat_server, "crypto_intel", SimpleNamespace(get_quick_signals=lambda symbols, timeframe="15m": []))
    asyncio.run(chat_server._telegram_reply_for_text("42", "/signals"))
    assert sent[-1][1] == "No signals available right now."

    asyncio.run(chat_server._telegram_reply_for_text("42", "/signal BTC"))
    assert sent[-1][1] == "signal:BTC:BTC"
    assert record_calls

    monkeypatch.setitem(sys.modules, "intelligence.tools.market_tools", SimpleNamespace(get_trading_tactics=lambda symbol: (_ for _ in ()).throw(RuntimeError("boom"))))
    asyncio.run(chat_server._telegram_reply_for_text("42", "/signal BTC"))
    assert "Analysis failed for BTC" in sent[-1][1]

    asyncio.run(chat_server._telegram_reply_for_text("42", "profile patch"))
    assert saved_profiles
    assert sent[-1][1] == "finance:profile patch:42"


def test_paper_trade_snapshot_and_misc_endpoint_wrappers(tmp_path, monkeypatch):
    db_path = tmp_path / "snapshot.db"
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB", str(db_path))
    monkeypatch.setattr(chat_server, "LEGACY_PERSISTENCE_DB", str(tmp_path / "legacy.db"))
    monkeypatch.setattr(chat_server, "PERSISTENCE_DB_FALLBACK", str(tmp_path / "fallback.db"))
    monkeypatch.setattr(chat_server, "_ACTIVE_PERSISTENCE_DB", str(db_path))
    chat_server.init_persistence_db()

    with chat_server.get_persistence_conn() as conn:
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                status, opened_at, entry_source, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
            """,
            ("open-1", "BTCUSD", "BUY", 1.0, 1.0, 100.0, 99.0, "2026-01-01T00:00:00+00:00", "auto_paper", "seed"),
        )
        conn.execute(
            """
            INSERT INTO paper_trades (
                id, symbol, side, quantity, volume, entry_price, current_price,
                exit_price, pnl, pnl_usd, status, opened_at, closed_at, outcome,
                entry_source, entry_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED', ?, ?, ?, ?, ?)
            """,
            ("closed-1", "ETHUSD", "SELL", 2.0, 2.0, 200.0, 180.0, 180.0, 40.0, 40.0, "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00", "WIN", "manual_api", "seed"),
        )
        conn.execute(
            "INSERT INTO trade_reviews (review_text, win_rate, score, created_at) VALUES (?, ?, ?, ?)",
            ("Good discipline", 0.75, 8.5, "2026-01-03T00:00:00+00:00"),
        )
        conn.commit()

    retrain_calls = []
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.outcome_tracker",
        SimpleNamespace(scan_and_update=lambda: {"closed_win": 1, "closed_loss": 0}),
    )
    monkeypatch.setattr(chat_server, "_maybe_trigger_auto_retrain", lambda reason: retrain_calls.append(reason))

    def _live_price(symbol):
        if symbol == "BTCUSD":
            return 105.5
        raise RuntimeError("mt5 down")

    monkeypatch.setattr(chat_server, "_get_live_price", _live_price)
    monkeypatch.setattr(chat_server, "_telegram_resolve_paper_entry_price", lambda symbol, side, fallback_price=None: 111.0)

    snapshot = chat_server._paper_trade_snapshot()
    assert snapshot["summary"]["open_count"] == 1
    assert snapshot["summary"]["closed_count"] == 1
    assert snapshot["open_trades"][0]["current_price"] == 105.5
    assert snapshot["total_simulated_pnl"] == snapshot["summary"]["closed_pnl_usd"]
    assert retrain_calls == ["paper_trade_auto_close"]

    monkeypatch.setattr(chat_server, "require_request_api_key", lambda request: None)
    monkeypatch.setattr(chat_server, "_ensure_trade_review_snapshots", lambda: retrain_calls.append("reviews_checked"))
    reviews = asyncio.run(chat_server.get_trade_reviews(SimpleNamespace()))
    assert reviews["reviews"][0]["review_text"] == "Good discipline"
    assert retrain_calls[-1] == "reviews_checked"

    monkeypatch.setattr(chat_server, "_pre_graph_rag_readiness", lambda: {"status": "ok", "blockers": []})
    readiness = asyncio.run(chat_server.rag_pre_graph_readiness(SimpleNamespace()))
    assert readiness == {"status": "ok", "blockers": []}

    monkeypatch.setattr(chat_server, "resolve_trade_symbol", lambda symbol: {"input": symbol, "normalized": symbol.upper()})
    resolved = asyncio.run(chat_server.api_resolve_trade_symbol(SimpleNamespace(), symbol="btcusd"))
    assert resolved["normalized"] == "BTCUSD"


def test_telegram_handle_update_and_poller(monkeypatch):
    sent = []
    answered = []
    replied = []
    deleted = []
    helper_calls = []
    feedback_calls = []

    async def _send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))

    async def _answer(callback_id, text):
        answered.append((callback_id, text))

    async def _confirm(chat_id, confirmation_id):
        helper_calls.append(("confirm", chat_id, confirmation_id))

    async def _cancel(chat_id, confirmation_id):
        helper_calls.append(("cancel", chat_id, confirmation_id))

    async def _paper(chat_id, confirmation_id):
        helper_calls.append(("paper", chat_id, confirmation_id))

    async def _scan(chat_id):
        helper_calls.append(("scan", chat_id))

    async def _reply(chat_id, text, user=None):
        replied.append((chat_id, text, user))

    monkeypatch.setattr(chat_server.notifier, "send_telegram_message", _send)
    monkeypatch.setattr(chat_server.notifier, "answer_callback_query", _answer)
    monkeypatch.setattr(chat_server.notifier, "is_chat_allowed", lambda chat_id: chat_id != "blocked")
    monkeypatch.setattr(chat_server, "_telegram_confirm_trade", _confirm)
    monkeypatch.setattr(chat_server, "_telegram_cancel_trade", _cancel)
    monkeypatch.setattr(chat_server, "_telegram_open_paper_from_confirmation", _paper)
    monkeypatch.setattr(chat_server, "_telegram_run_paper_scan", _scan)
    monkeypatch.setattr(chat_server, "_telegram_reply_for_text", _reply)
    monkeypatch.setattr(chat_server, "_telegram_format_blocked_detail", lambda confirmation_id: f"detail:{confirmation_id}")
    monkeypatch.setattr(chat_server, "_telegram_blocked_trade_keyboard", lambda confirmation_id: {"blocked": confirmation_id})
    monkeypatch.setattr(chat_server, "_telegram_format_best_explain", lambda chat_id=None: f"explain:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_best_feedback_keyboard", lambda chat_id=None: {"best": chat_id})
    monkeypatch.setattr(chat_server, "_telegram_format_no_trade_reason", lambda chat_id=None: f"no-trade:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_format_best_metrics", lambda: "metrics")
    monkeypatch.setattr(chat_server, "_telegram_format_risk_guard", lambda chat_id=None: f"risk:{chat_id}")
    monkeypatch.setattr(chat_server, "_telegram_keyboard", lambda: {"main": True})
    monkeypatch.setattr(chat_server, "_telegram_create_best_entry_alert", lambda chat_id: {"id": 1, "symbol": "BTCUSD", "side": "BUY", "condition": "above", "price": 100.0, "decision": "GO", "no_trade": True, "no_trade_reason": "cooldown"})
    monkeypatch.setattr(chat_server, "_telegram_create_best_confirmation_alert", lambda chat_id: (_ for _ in ()).throw(RuntimeError("confirm boom")))
    monkeypatch.setattr(chat_server, "_telegram_save_setup_feedback", lambda chat_id, rating, symbol, side: feedback_calls.append((chat_id, rating, symbol, side)) or {"saved": True})
    monkeypatch.setattr(chat_server, "_telegram_audit", lambda *args, **kwargs: helper_calls.append(("audit", args, kwargs)))
    monkeypatch.setattr(chat_server, "_best_setup_cache", {})

    unauthorized_callback = {
        "callback_query": {"id": "cb-0", "data": "tg:best", "message": {"chat": {"id": "blocked"}}}
    }
    asyncio.run(chat_server._telegram_handle_update(unauthorized_callback))
    assert answered[-1] == ("cb-0", "Working...")
    assert sent[-1][1] == "This chat is not authorized."

    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-1", "data": "tg:trade_confirm:abc", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-2", "data": "tg:trade_cancel:def", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-3", "data": "tg:why_blocked:ghi", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-4", "data": "tg:paper_trade:jkl", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-5", "data": "tg:paper_scan", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-6", "data": "tg:best_explain", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-7", "data": "tg:no_trade", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-8", "data": "tg:best_metrics", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-9", "data": "tg:risk_guard", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-10", "data": "tg:best_alert", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-11", "data": "tg:best_confirm_alert", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-12", "data": "tg:setup_fb:GOOD:BTCUSD:BUY", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-13", "data": "tg:status", "message": {"chat": {"id": "42"}}}}))
    asyncio.run(chat_server._telegram_handle_update({"callback_query": {"id": "cb-14", "data": "tg:unknown", "message": {"chat": {"id": "42"}}}}))

    assert ("confirm", "42", "abc") in helper_calls
    assert ("cancel", "42", "def") in helper_calls
    assert ("paper", "42", "jkl") in helper_calls
    assert ("scan", "42") in helper_calls
    assert any(item[1] == "detail:ghi" for item in sent)
    assert any(item[1] == "explain:42" for item in sent)
    assert any(item[1] == "no-trade:42" for item in sent)
    assert any(item[1] == "metrics" for item in sent)
    assert any(item[1] == "risk:42" for item in sent)
    assert any("Entry alert created." in item[1] and "NO TRADE" in item[1] for item in sent)
    assert any(item[1] == "Confirmation alert failed: confirm boom" for item in sent)
    assert feedback_calls == [("42", "GOOD", "BTCUSD", "BUY")]
    assert ("42", "/status", None) in replied
    assert ("42", "/help", None) in replied

    sent.clear()
    replied.clear()
    asyncio.run(chat_server._telegram_handle_update({"message": {"chat": {"id": "blocked"}, "text": "/help", "from": {"id": 1}}}))
    assert sent[-1][1] == "This chat is not authorized."

    asyncio.run(chat_server._telegram_handle_update({"message": {"chat": {"id": "42"}, "text": "  /best  ", "from": {"id": 7}}}))
    assert replied[-1][0] == "42"
    assert replied[-1][1] == "/best"
    assert replied[-1][2] == {"id": 7}

    asyncio.run(chat_server._telegram_handle_update({"message": {"chat": {"id": "42"}, "text": ""}}))
    assert replied[-1][1] == "/best"

    async def _delete_webhook():
        deleted.append("webhook")

    class Poller:
        def __init__(self):
            self.calls = 0

        async def get_updates(self, timeout=20, limit=20):
            self.calls += 1
            if self.calls == 1:
                return [{"message": {"chat": {"id": "42"}, "text": "/status", "from": {"id": 9}}}]
            raise asyncio.CancelledError()

    poller = Poller()
    monkeypatch.setenv("TELEGRAM_BOT_POLLING_ENABLED", "1")
    monkeypatch.setattr(chat_server.notifier, "telegram_status", lambda: {"polling_ready": True})
    monkeypatch.setattr(chat_server.notifier, "delete_webhook", _delete_webhook)
    monkeypatch.setattr(chat_server.notifier, "get_updates", poller.get_updates)

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(chat_server.asyncio, "sleep", _no_sleep)
    try:
        asyncio.run(chat_server.telegram_bot_poller_task())
        raise AssertionError("expected poller cancellation")
    except asyncio.CancelledError:
        pass

    assert deleted == ["webhook"]
    assert ("42", "/status", {"id": 9}) in replied
