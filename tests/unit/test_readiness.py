import types
import sys

import pandas as pd

from intelligence.ml import readiness


def test_paper_db_path_reads_env(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: "custom.db" if key == "PAPER_TRADE_DB" else default)

    assert readiness._paper_db_path() == "custom.db"


def test_load_model_bundle_success_and_failure(monkeypatch):
    fake_signal_model = types.SimpleNamespace(_load_model=lambda: {"bundle": True})
    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", fake_signal_model)
    assert readiness._load_model_bundle() == {"bundle": True}

    fake_broken_signal_model = types.SimpleNamespace(_load_model=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", fake_broken_signal_model)
    assert readiness._load_model_bundle() is None


def test_get_paper_trade_performance_handles_missing_db(monkeypatch):
    monkeypatch.setattr(readiness, "_paper_db_path", lambda: "missing.db")
    monkeypatch.setattr(readiness.os.path, "exists", lambda path: False)

    result = readiness.get_paper_trade_performance()

    assert result["available"] is False
    assert result["total"] == 0


def test_get_paper_trade_performance_handles_query_error(monkeypatch):
    monkeypatch.setattr(readiness, "_paper_db_path", lambda: "paper.db")
    monkeypatch.setattr(readiness.os.path, "exists", lambda path: True)
    monkeypatch.setattr(readiness.sqlite3, "connect", lambda path: object())
    monkeypatch.setattr(readiness.pd, "read_sql_query", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("bad query")))

    result = readiness.get_paper_trade_performance()

    assert result["available"] is False
    assert "bad query" in result["error"]


def test_get_paper_trade_performance_handles_empty_frame(monkeypatch):
    class FakeConn:
        def close(self):
            return None

    monkeypatch.setattr(readiness, "_paper_db_path", lambda: "paper.db")
    monkeypatch.setattr(readiness.os.path, "exists", lambda path: True)
    monkeypatch.setattr(readiness.sqlite3, "connect", lambda path: FakeConn())
    monkeypatch.setattr(readiness.pd, "read_sql_query", lambda *args, **kwargs: pd.DataFrame())

    result = readiness.get_paper_trade_performance()

    assert result["available"] is True
    assert result["total"] == 0


def test_get_paper_trade_performance_summarizes_metrics(monkeypatch):
    class FakeConn:
        def close(self):
            return None

    frame = pd.DataFrame(
        [
            {"symbol": "BTCUSD", "outcome": "WIN", "pnl_usd": 10.0, "closed_at": "2026-05-25"},
            {"symbol": "BTCUSD", "outcome": "LOSS", "pnl_usd": -5.0, "closed_at": "2026-05-26"},
            {"symbol": "ETHUSD", "outcome": "WIN", "pnl_usd": 15.0, "closed_at": "2026-05-27"},
        ]
    )
    monkeypatch.setattr(readiness, "_paper_db_path", lambda: "paper.db")
    monkeypatch.setattr(readiness.os.path, "exists", lambda path: True)
    monkeypatch.setattr(readiness.sqlite3, "connect", lambda path: FakeConn())
    monkeypatch.setattr(readiness.pd, "read_sql_query", lambda *args, **kwargs: frame)

    result = readiness.get_paper_trade_performance()

    assert result["available"] is True
    assert result["total"] == 3
    assert result["wins"] == 2
    assert result["profit_factor"] == 5.0
    assert result["by_symbol"][0]["symbol"] == "BTCUSD"


def test_get_model_quality_summary_handles_missing_bundle():
    original_loader = readiness._load_model_bundle
    readiness._load_model_bundle = lambda: None
    assert readiness.get_model_quality_summary(None) == {"available": False}
    readiness._load_model_bundle = original_loader


def test_get_model_quality_summary_extracts_expected_fields():
    bundle = {
        "n_samples": 2000,
        "accuracy": 0.6,
        "roc_auc": 0.55,
        "walk_forward": {"summary": {"avg_roc_auc": 0.57}},
        "calibration": {"available": True, "brier_score": 0.2, "ece": 0.03},
        "sufficiency": {"ready_for_improvement": True},
        "dataset_quality": {"ok": True},
        "slice_pruning": {"enabled": True},
    }

    result = readiness.get_model_quality_summary(bundle)

    assert result["available"] is True
    assert result["n_samples"] == 2000
    assert result["walk_forward"]["avg_roc_auc"] == 0.57
    assert result["calibration"]["brier_score"] == 0.2


def test_reason_helper_wraps_fields():
    assert readiness._reason(True, "ready", "all good") == {
        "ok": True,
        "name": "ready",
        "detail": "all good",
    }


def test_audit_mt5_history_handles_missing_package(monkeypatch):
    fake_module = types.SimpleNamespace(_MT5_AVAILABLE=False, mt5_get_rates=lambda *args, **kwargs: None)
    monkeypatch.setitem(__import__("sys").modules, "intelligence.mt5_connector", fake_module)

    result = readiness.audit_mt5_history()

    assert result["available"] is False
    assert result["passed"] is False


def test_audit_mt5_history_handles_import_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "intelligence.mt5_connector", None)
    original_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "intelligence.mt5_connector":
            raise RuntimeError("import failed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    result = readiness.audit_mt5_history()

    assert result["available"] is False
    assert result["passed"] is False
    assert "import failed" in result["error"]


def test_audit_mt5_history_collects_symbol_issues(monkeypatch):
    original_thresholds = readiness.ReadinessThresholds
    fake_module = types.SimpleNamespace(
        _MT5_AVAILABLE=True,
        mt5_get_rates=lambda symbol, timeframe, count: pd.DataFrame(
            {"Datetime": [1, 1], "Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [10]}
        )
        if symbol == "BTCUSD"
        else None,
    )
    monkeypatch.setitem(__import__("sys").modules, "intelligence.mt5_connector", fake_module)
    monkeypatch.setattr(readiness, "ReadinessThresholds", lambda: original_thresholds(min_mt5_bars=5))

    result = readiness.audit_mt5_history(symbols=[("BTCUSD", "1h"), ("ETHUSD", "1h")], count=10)

    assert result["available"] is True
    assert result["passed"] is False
    assert result["symbols"][0]["issues"]
    assert result["symbols"][1]["issues"] == ["no_history"]


def test_audit_mt5_history_passes_with_clean_rows(monkeypatch):
    fake_module = types.SimpleNamespace(
        _MT5_AVAILABLE=True,
        mt5_get_rates=lambda symbol, timeframe, count: pd.DataFrame(
            {
                "Datetime": pd.date_range("2026-01-01", periods=5, freq="h"),
                "Open": [1, 2, 3, 4, 5],
                "High": [2, 3, 4, 5, 6],
                "Low": [0, 1, 2, 3, 4],
                "Close": [1.5, 2.5, 3.5, 4.5, 5.5],
                "Volume": [10, 11, 12, 13, 14],
            }
        ),
    )
    monkeypatch.setitem(sys.modules, "intelligence.mt5_connector", fake_module)
    original_thresholds = readiness.ReadinessThresholds
    monkeypatch.setattr(readiness, "ReadinessThresholds", lambda: original_thresholds(min_mt5_bars=5))

    result = readiness.audit_mt5_history(symbols=[("BTCUSD", "1h")], count=5)

    assert result["available"] is True
    assert result["passed"] is True
    assert result["symbols"][0]["ok"] is True
    assert result["symbols"][0]["rows"] == 5


def test_audit_mt5_history_flags_bar_count_duplicates_and_missing_columns(monkeypatch):
    fake_module = types.SimpleNamespace(
        _MT5_AVAILABLE=True,
        mt5_get_rates=lambda symbol, timeframe, count: pd.DataFrame(
            {
                "Datetime": pd.to_datetime(["2026-01-01", "2026-01-01"]),
                "Open": [1, 2],
                "High": [2, 3],
                "Low": [0, 1],
            }
        ),
    )
    monkeypatch.setitem(sys.modules, "intelligence.mt5_connector", fake_module)
    original_thresholds = readiness.ReadinessThresholds
    monkeypatch.setattr(readiness, "ReadinessThresholds", lambda: original_thresholds(min_mt5_bars=5))

    result = readiness.audit_mt5_history(symbols=[("BTCUSD", "1h")], count=2)

    issues = result["symbols"][0]["issues"]
    assert "bars<5" in issues
    assert "duplicate_timestamps" in issues
    assert "missing:Close,Volume" in issues


def test_evaluate_readiness_returns_pass_report(monkeypatch):
    monkeypatch.setattr(readiness, "_load_model_bundle", lambda: {"n_samples": 2000})
    monkeypatch.setattr(
        readiness,
        "get_model_quality_summary",
        lambda bundle=None: {
            "available": True,
            "n_samples": 2000,
            "roc_auc": 0.55,
            "walk_forward": {"avg_roc_auc": 0.56},
            "calibration": {"brier_score": 0.2},
            "sufficiency": {"ready_for_improvement": True},
        },
    )
    monkeypatch.setattr(
        readiness,
        "get_paper_trade_performance",
        lambda limit=300: {"total": 50, "profit_factor": 1.5, "expectancy_usd": 1.0},
    )
    monkeypatch.setattr(readiness, "get_feedback_snapshot", lambda: {"ok": True})
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.signal_model",
        types.SimpleNamespace(get_live_sufficiency_status=lambda bundle: {"ready_for_improvement": True, "progress": {"overall": 1.0}}),
    )

    report = readiness.evaluate_readiness(require_mt5_audit=False)

    assert report["passed"] is True
    assert report["blockers"] == []


def test_evaluate_readiness_handles_fallback_sufficiency_and_mt5_audit(monkeypatch):
    monkeypatch.setattr(readiness, "_load_model_bundle", lambda: {"n_samples": 100})
    monkeypatch.setattr(
        readiness,
        "get_model_quality_summary",
        lambda bundle=None: {
            "available": False,
            "n_samples": 100,
            "roc_auc": 0.4,
            "walk_forward": {"avg_roc_auc": 0.4},
            "calibration": {"brier_score": 0.5},
            "sufficiency": {"ready_for_improvement": False, "progress": {"overall": 0.2}},
        },
    )
    monkeypatch.setattr(
        readiness,
        "get_paper_trade_performance",
        lambda limit=300: {"total": 2, "profit_factor": 0.8, "expectancy_usd": -1.0},
    )
    monkeypatch.setattr(readiness, "get_feedback_snapshot", lambda: {"ok": False})
    monkeypatch.setitem(
        sys.modules,
        "intelligence.ml.signal_model",
        types.SimpleNamespace(get_live_sufficiency_status=lambda bundle: (_ for _ in ()).throw(RuntimeError("no sufficiency"))),
    )
    monkeypatch.setattr(readiness, "audit_mt5_history", lambda symbols=None: {"passed": False, "symbols": [], "available": True})

    report = readiness.evaluate_readiness(require_mt5_audit=True, mt5_symbols=[("BTCUSD", "1h")])

    assert report["passed"] is False
    assert report["mt5_audit"]["passed"] is False
    assert any(check["name"] == "mt5_history" for check in report["checks"])


def test_evaluate_readiness_uses_paper_override_for_walk_forward(monkeypatch):
    monkeypatch.setattr(readiness, "_load_model_bundle", lambda: {"n_samples": 2000})
    monkeypatch.setattr(
        readiness,
        "get_model_quality_summary",
        lambda bundle=None: {
            "available": True,
            "n_samples": 2000,
            "roc_auc": 0.55,
            "walk_forward": {"avg_roc_auc": 0.505},
            "calibration": {"brier_score": 0.2},
            "sufficiency": {"ready_for_improvement": True},
        },
    )
    monkeypatch.setattr(
        readiness,
        "get_paper_trade_performance",
        lambda limit=300: {"total": 50, "profit_factor": 1.5, "expectancy_usd": 1.0},
    )
    monkeypatch.setattr(readiness, "get_feedback_snapshot", lambda: {})
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.signal_model",
        types.SimpleNamespace(get_live_sufficiency_status=lambda bundle: {"ready_for_improvement": True, "progress": {"overall": 1.0}}),
    )

    report = readiness.evaluate_readiness()

    names = {check["name"]: check["ok"] for check in report["checks"]}
    assert names["walk_forward_auc"] is True


def test_live_execution_gate_allows_override(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: "1" if key == "ALLOW_UNREADY_LIVE_TRADING" else default)
    monkeypatch.setattr(readiness, "evaluate_readiness", lambda require_mt5_audit=False, mt5_symbols=None: {"passed": False})

    allowed, report = readiness.live_execution_gate()

    assert allowed is True
    assert report["override"] == "ALLOW_UNREADY_LIVE_TRADING"


def test_live_execution_gate_without_symbol_returns_base_report(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: default)
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda require_mt5_audit=False, mt5_symbols=None: {"passed": True, "checks": [], "blockers": [], "mt5_symbols": mt5_symbols},
    )

    allowed, report = readiness.live_execution_gate(None, require_mt5_audit=True)

    assert allowed is True
    assert report["mt5_symbols"] is None


def test_live_execution_gate_appends_feedback_checks(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: default)
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda require_mt5_audit=False, mt5_symbols=None: {"passed": True, "checks": [], "blockers": []},
    )
    monkeypatch.setattr(
        readiness,
        "score_signal_feedback",
        lambda symbol, entry_source, side=None: {
            "source_stats": {"trades": 12, "win_rate": 0.6, "pnl": 20},
            "symbol_stats": {"trades": 6, "win_rate": 0.7, "pnl": 10},
            "symbol_side_stats": {"trades": 4, "win_rate": 0.2, "pnl": -5},
            "readiness": {"source_ready": True, "symbol_ready": True, "symbol_side_ready": False},
            "notes": ["watch short side"],
        },
    )

    allowed, report = readiness.live_execution_gate({"symbol": "BTCUSD", "timeframe": "1h", "side": "SELL"})

    assert allowed is False
    assert report["signal_feedback"]["symbol"] == "BTCUSD"
    assert any(check["name"] == "performance_symbol_side_ready" for check in report["checks"])


def test_live_execution_gate_parses_state_and_skips_feedback_thresholds(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: "1" if key == "ML_REQUIRE_MT5_AUDIT_FOR_LIVE" else default)
    captured = {}
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda require_mt5_audit=False, mt5_symbols=None: captured.setdefault(
            "report",
            {"passed": True, "checks": [], "blockers": [], "mt5_symbols": mt5_symbols, "require_mt5_audit": require_mt5_audit},
        ),
    )
    monkeypatch.setattr(
        readiness,
        "score_signal_feedback",
        lambda symbol, entry_source, side=None: {
            "source_stats": {"trades": 9, "win_rate": 0.6, "pnl": 20},
            "symbol_stats": {"trades": 4, "win_rate": 0.7, "pnl": 10},
            "symbol_side_stats": {"trades": 2, "win_rate": 0.5, "pnl": 1},
            "readiness": {"source_ready": True, "symbol_ready": True, "symbol_side_ready": True},
            "notes": [],
        },
    )

    allowed, report = readiness.live_execution_gate({"symbol": "ethusd", "timeframe": "4h", "master_decision": "short"})

    assert allowed is True
    assert report["signal_feedback"]["symbol"] == "ETHUSD"
    assert report["signal_feedback"]["side"] == "SELL"
    assert report["mt5_symbols"] == [("ETHUSD", "4h")]
    assert report["require_mt5_audit"] is True
    assert report["checks"] == []


def test_live_execution_gate_maps_long_to_buy_and_state_without_symbol(monkeypatch):
    calls = []
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: default)
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda require_mt5_audit=False, mt5_symbols=None: calls.append((require_mt5_audit, mt5_symbols)) or {"passed": True, "checks": [], "blockers": []},
    )
    monkeypatch.setattr(
        readiness,
        "score_signal_feedback",
        lambda symbol, entry_source, side=None: {
            "source_stats": {"trades": 0},
            "symbol_stats": {"trades": 0},
            "symbol_side_stats": {"trades": 0},
            "readiness": {},
            "notes": [],
        },
    )

    allowed, report = readiness.live_execution_gate({"symbol": "btcusd", "action": "long", "timeframe": "15m"})

    assert allowed is True
    assert report["signal_feedback"]["side"] == "BUY"
    assert calls[0] == (False, [("BTCUSD", "15m")])

    calls.clear()
    allowed, report = readiness.live_execution_gate({"action": "buy", "timeframe": "15m"})

    assert allowed is True
    assert "signal_feedback" not in report
    assert calls[0] == (False, None)


def test_live_execution_gate_keeps_unknown_side_empty(monkeypatch):
    monkeypatch.setattr(readiness.os, "getenv", lambda key, default=None: default)
    monkeypatch.setattr(
        readiness,
        "evaluate_readiness",
        lambda require_mt5_audit=False, mt5_symbols=None: {"passed": True, "checks": [], "blockers": []},
    )
    captured = {}
    def fake_score_signal_feedback(symbol, entry_source, side=None):
        captured["feedback"] = (symbol, entry_source, side)
        return {
            "source_stats": {"trades": 0},
            "symbol_stats": {"trades": 0},
            "symbol_side_stats": {"trades": 0},
            "readiness": {},
            "notes": [],
        }

    monkeypatch.setattr(readiness, "score_signal_feedback", fake_score_signal_feedback)

    allowed, report = readiness.live_execution_gate({"symbol": "btcusd", "action": "hold"})

    assert allowed is True
    assert captured["feedback"] == ("BTCUSD", "signal_feed_analysis", None)
    assert report["signal_feedback"]["side"] == ""


def test_print_readiness_json_outputs_serializable_payload(capsys):
    readiness.print_readiness_json({"a": 1})
    captured = capsys.readouterr()
    assert '"a": 1' in captured.out
