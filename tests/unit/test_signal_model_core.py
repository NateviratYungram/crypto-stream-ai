import json
import pickle
import sqlite3
from types import SimpleNamespace

import numpy as np
import pandas as pd

from intelligence.ml import signal_model as sm


def _feature_row(**overrides):
    row = {col: 1.0 for col in sm.FEATURE_COLS}
    row.update(
        {
            "rsi": 50.0,
            "adx": 25.0,
            "atr_pct": 1.0,
            "bb_pct": 0.5,
            "vol_ratio": 1.0,
        }
    )
    row.update(overrides)
    return row


def _signal_frame(direction="buy", rows=30):
    close = np.linspace(100, 120, rows) if direction == "buy" else np.linspace(120, 100, rows)
    df = pd.DataFrame(
        {
            "Close": close,
            "High": close + 1,
            "Low": close - 1,
            "Open": close - 0.2 if direction == "buy" else close + 0.2,
            "rsi_14": 50 if direction == "buy" else 45,
            "ema_20": close - 1 if direction == "buy" else close + 1,
            "ema_50": close - 2 if direction == "buy" else close + 2,
            "adx_14": 30,
            "atr_14": 1.2,
            "macd_hist": 0.5 if direction == "buy" else -0.5,
        },
        index=pd.date_range("2026-01-01", periods=rows, freq="h"),
    )
    return df


def test_prepare_training_frame_drops_bad_rows_and_normalizes_volume():
    df = pd.DataFrame(
        {
            "Open": [1, 2, -1, 4, 5],
            "High": [2, 1, 3, np.inf, 6],
            "Low": [0.5, 1, 1, 2, 4],
            "Close": [1.5, "bad", 2, 3, 5],
            "Volume": [10, -5, None, 20, 30],
        },
        index=[2, 1, 1, 4, 3],
    )

    result = sm._prepare_training_frame(df)

    assert len(result) == 2
    assert result.index.tolist() == [2, 3]
    assert result["Volume"].min() >= 0


def test_prepare_training_frame_rejects_missing_or_empty_input():
    assert sm._prepare_training_frame(None).empty
    assert sm._prepare_training_frame(pd.DataFrame()).empty
    assert sm._prepare_training_frame(pd.DataFrame({"Open": [1]})).empty


def test_feature_row_validation_catches_bounds_and_non_numeric_values():
    assert sm._is_valid_feature_row(_feature_row()) is True
    assert sm._is_valid_feature_row(_feature_row(atr_pct=0)) is False
    assert sm._is_valid_feature_row(_feature_row(adx=101)) is False
    assert sm._is_valid_feature_row(_feature_row(rsi=-1)) is False
    assert sm._is_valid_feature_row(_feature_row(bb_pct=2)) is False
    assert sm._is_valid_feature_row(_feature_row(vol_ratio=30)) is False
    assert sm._is_valid_feature_row(_feature_row(rsi="nan-ish")) is False


def test_generate_training_signals_creates_buy_and_sell_with_cooldown():
    buy = sm._generate_training_signals(_signal_frame("buy"), "1h")
    sell = sm._generate_training_signals(_signal_frame("sell"), "1h")

    assert set(buy["signal"]) == {0, 1}
    assert set(sell["signal"]) == {0, -1}
    assert buy["signal"].sum() < len(buy)
    assert abs(sell["signal"].sum()) < len(sell)


def test_generate_training_signals_returns_unchanged_when_required_columns_missing():
    df = pd.DataFrame({"Close": [1, 2, 3]})

    result = sm._generate_training_signals(df, "1h")

    assert "signal" not in result.columns


def test_daily_and_vix_context_builders(monkeypatch):
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    daily_rows = {
        dates[0].date(): pd.Series({"Close": 100, "ema_20": 99, "ema_50": 98, "ema_200": 90, "rsi_14": 60}),
        dates[1].date(): pd.Series({"Close": 90, "ema_20": 95, "ema_50": 100, "ema_200": 110, "rsi_14": 40}),
    }
    h4_rows = {
        dates[0].date(): pd.Series({"Close": 101, "ema_20": 100, "ema_50": 99}),
        dates[1].date(): pd.Series({"Close": 89, "ema_20": 90, "ema_50": 91}),
    }
    monkeypatch.setattr(sm, "_build_htf_bars", lambda symbol, asset_class, timeframe, limit=5000: daily_rows if timeframe == "1d" else h4_rows)
    monkeypatch.setattr(sm, "_build_vix_context", lambda: {dates[0].date(): 30, dates[1].date(): 40})

    context = sm._build_daily_context("BTC", "CRYPTO")

    assert context[dates[0].date()]["d_bullish"] is True
    assert context[dates[0].date()]["h4_bullish"] is True
    assert context[dates[0].date()]["vix_risk_off"] is True
    assert context[dates[1].date()]["d_bearish"] is True
    assert context[dates[1].date()]["h4_bearish"] is True
    assert context[dates[1].date()]["vix_crisis"] is True


def test_scan_paper_trade_outcomes_counts_included_and_excluded(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE paper_trades (
                id TEXT, symbol TEXT, side TEXT, entry_price REAL, sl REAL, tp REAL,
                outcome TEXT, features_json TEXT, closed_at TEXT, opened_at TEXT,
                pnl_usd REAL, entry_source TEXT, close_reason TEXT, status TEXT
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("t1", "BTCUSD", "BUY", 100, 90, 120, "WIN", json.dumps(_feature_row()), "2026-01-01", None, 5, "auto_paper", "tp", "CLOSED"),
                ("t2", "ETHUSD", "SELL", 100, 110, 80, "LOSS", json.dumps(_feature_row()), "2026-01-02", None, -2, "manual", "sl", "CLOSED"),
                ("t3", "SOLUSD", "BUY", 100, 90, 120, "OPEN", json.dumps(_feature_row()), "2026-01-03", None, 0, "auto_paper", "none", "CLOSED"),
            ],
        )
        conn.commit()

    def decision(row, features):
        include = row["id"] == "t1"
        return {
            "include": include,
            "reasons": [] if include else ["source_not_allowed"],
            "entry_source": row["entry_source"],
            "symbol": row["symbol"],
            "side": row["side"],
            "pnl_usd": row["pnl_usd"],
            "performance_gate": {"blockers": ["manual_source"]},
        }

    monkeypatch.setattr(sm, "PAPER_DB_PATH", str(db_path))
    monkeypatch.setattr(sm, "_paper_label_quality_decision", decision)

    rows, report = sm._scan_paper_trade_outcomes()

    assert len(rows) == 1
    assert rows[0]["label"] == 1
    assert report["included"] == 1
    assert report["excluded"] == 1
    assert report["reasons"]["source_not_allowed"] == 1
    assert report["examples"][0]["trade_id"] == "t2"


def test_cached_dataset_with_fresh_paper_labels_appends_quality_rows(tmp_path, monkeypatch):
    dataset_path = tmp_path / "dataset.parquet"
    base = pd.DataFrame(
        [
            {"symbol": "BTC", "timeframe": "1h", "entry_source": None, "label": 1, **_feature_row()},
            {"symbol": "PAPER", "timeframe": "paper", "entry_source": "auto_paper", "label": 0, **_feature_row()},
        ]
    )
    base.to_parquet(dataset_path, index=False)
    monkeypatch.setattr(sm, "DATASET_PATH", dataset_path)
    monkeypatch.setattr(sm, "_load_paper_trade_outcomes", lambda: [{"symbol": "ETH", "timeframe": "paper", "label": 0, **_feature_row()}])

    result = sm._cached_dataset_with_fresh_paper_labels()

    assert result is not None
    assert set(result["symbol"]) == {"BTC", "ETH"}


def test_live_sufficiency_status_uses_bundle_and_db_count(tmp_path, monkeypatch):
    db_path = tmp_path / "paper.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE paper_trades (outcome TEXT, status TEXT)")
        conn.executemany("INSERT INTO paper_trades VALUES (?, ?)", [("WIN", "CLOSED"), ("LOSS", "CLOSED")])
        conn.commit()

    monkeypatch.setattr(sm, "PAPER_DB_PATH", str(db_path))
    monkeypatch.setattr(sm, "ML_SUFFICIENCY_TARGETS", {"paper_labels": 2, "training_samples": 10, "core_symbols": 2})
    monkeypatch.setattr(sm, "ML_CORE_SYMBOLS", ["BTCUSD", "ETHUSD"])

    status = sm.get_live_sufficiency_status(
        {
            "dataset_report": [{"symbol": "BTCUSD"}, {"symbol": "ETHUSD"}],
            "n_samples": 10,
            "outcomes_at_retrain": 0,
        }
    )

    assert status["progress"]["overall"] == 1.0
    assert status["ready_for_improvement"] is True


def test_walk_forward_evaluate_runs_small_expanding_windows():
    from sklearn.linear_model import LogisticRegression

    X = np.array([[i, i % 3] for i in range(120)], dtype=float)
    y = np.array([0, 1] * 60)

    result = sm._walk_forward_evaluate(
        LogisticRegression(max_iter=200),
        X,
        y,
        min_train_size=20,
        test_window=10,
        max_folds=3,
    )

    assert result["available"] is False


def test_wrappers_delegate_to_support_helpers(monkeypatch):
    report = {"reasons": {}}
    sm._count_reason(report, "thin_slice")

    assert report["reasons"]["thin_slice"] == 1
    assert sm._normalize_paper_symbol("btcusdt") == "BTCUSD"
    assert sm._paper_feature_coverage(_feature_row()) >= 10
    assert sm._build_dataset_report(pd.DataFrame([{"symbol": "BTC", "timeframe": "1h", "label": 1}, {"symbol": "BTC", "timeframe": "1h", "label": 0}]))
    assert sm._build_calibration_profile(np.array([0, 1]), np.array([0.2, 0.8]))["available"] is True
    assert 0.0 <= sm._apply_calibration(0.5, {"available": False}) <= 1.0


def test_quality_report_cache_and_cached_dataset_failures(tmp_path, monkeypatch):
    calls = []

    def _scan():
        calls.append("scan")
        return [], {"available": True, "included": 0, "excluded": 0}

    monkeypatch.setattr(sm, "_scan_paper_trade_outcomes", _scan)
    sm._LAST_PAPER_LABEL_QUALITY_REPORT = {"available": False}
    first = sm.get_paper_label_quality_report()
    second = sm.get_paper_label_quality_report()
    forced = sm.get_paper_label_quality_report(force_refresh=True)

    assert first["available"] is True
    assert second == first
    assert forced == first
    assert calls == ["scan", "scan"]

    missing = tmp_path / "missing.parquet"
    monkeypatch.setattr(sm, "DATASET_PATH", missing)
    assert sm._cached_dataset_with_fresh_paper_labels() is None

    broken = tmp_path / "broken.parquet"
    broken.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sm, "DATASET_PATH", broken)
    monkeypatch.setattr(sm.pd, "read_parquet", lambda path: (_ for _ in ()).throw(RuntimeError("broken parquet")))
    assert sm._cached_dataset_with_fresh_paper_labels() is None


def test_load_model_and_predict_win_probability_paths(tmp_path, monkeypatch):
    model_path = tmp_path / "model.pkl"
    monkeypatch.setattr(sm, "MODEL_PATH", model_path)
    sm._MODEL_CACHE = None

    unavailable = sm.predict_win_probability({"rsi": 50})
    assert unavailable["available"] is False
    assert unavailable["win_probability"] == 0.5

    class FakeModel:
        def predict_proba(self, rows):
            return np.array([[0.2, 0.8]])

    class BrokenIso:
        def transform(self, values):
            raise RuntimeError("iso down")

    bundle = {
        "model": FakeModel(),
        "feature_cols": ["rsi", "adx"],
        "n_samples": 123,
        "accuracy": 0.61,
        "roc_auc": 0.71,
        "trained_at": "2026-01-01T00:00:00+00:00",
        "feature_importance": [{"feature": "rsi", "label": "RSI Edge"}, {"feature": "adx", "label": "ADX Trend"}],
        "isotonic_calibrator": BrokenIso(),
        "calibration": {"available": True},
    }
    model_path.write_bytes(b"bundle")
    monkeypatch.setattr(sm.pickle, "load", lambda fh: bundle)

    applied = []
    monkeypatch.setattr(sm, "_apply_calibration", lambda prob, calibration: applied.append((prob, calibration)) or 0.65)

    loaded = sm._load_model()
    cached = sm._load_model()
    predicted = sm.predict_win_probability({"rsi": 80.0, "adx": 30.0, "hurst_exponent": 0.6, "vol_skew": 0.1})

    assert loaded is cached
    assert predicted["available"] is True
    assert predicted["win_probability"] == 0.65
    assert predicted["raw_win_probability"] == 0.8
    assert predicted["win_pct"] == 65.0
    assert predicted["n_samples"] == 123
    assert predicted["rationale"][:2] == ["RSI Edge", "ADX Trend"]
    assert applied and applied[0][0] == 0.8

    sm.invalidate_model_cache()
    assert sm._MODEL_CACHE is None

    model_path.write_bytes(b"not-a-pickle")
    monkeypatch.setattr(sm.pickle, "load", lambda fh: (_ for _ in ()).throw(RuntimeError("bad pickle")))
    assert sm._load_model() is None


def test_predict_with_neural_consensus_block_and_risk_paths(monkeypatch):
    df = pd.DataFrame({"Close": np.linspace(100, 140, 25)}, index=pd.date_range("2026-01-01", periods=25, freq="h"))

    monkeypatch.setattr(sm, "_consider_auto_retrain", lambda: None)
    monkeypatch.setattr(sm, "_build_daily_context", lambda symbol, asset_class: {df.index[5].date(): {"d_bullish": False, "h4_bullish": False, "vix_crisis": False, "vix_risk_off": False, "vix": 15}})
    monkeypatch.setattr(sm, "extract_features", lambda *args, **kwargs: {"rsi": 1.0, "adx": 2.0})
    monkeypatch.setattr(sm, "predict_win_probability", lambda features: {"win_probability": 0.81, "direction": "BUY", "win_pct": 81.0})

    blocked = sm.predict_with_neural_consensus(df, 5, side="BUY", symbol="BTCUSD", asset_class="CRYPTO")
    assert blocked["direction"] == "HOLD"
    assert blocked["mtf_blocked"] is True

    monkeypatch.setattr(
        sm,
        "_build_daily_context",
        lambda symbol, asset_class: {
            df.index[20].date(): {"d_bullish": True, "h4_bullish": True, "d_bearish": False, "h4_bearish": False, "vix_crisis": False, "vix_risk_off": False, "vix": 18}
        },
    )
    monkeypatch.setattr(sm, "TORCH_AVAILABLE", False)
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.technical_engine",
        SimpleNamespace(get_smart_money_analysis=lambda frame: {"structure": "bullish"}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.risk_manager",
        SimpleNamespace(full_risk_check=lambda **kwargs: {"ok": False, "blocked_by": ["risk-cap"]}),
    )
    risk_blocked = sm.predict_with_neural_consensus(df, 20, side="BUY", symbol="BTCUSD", asset_class="CRYPTO")
    assert risk_blocked["direction"] == "HOLD"
    assert risk_blocked["risk_blocked"] is True
    assert "risk-cap" in risk_blocked["risk_reason"]


def test_predict_with_neural_consensus_neural_alignment_and_auto_retrain_status(tmp_path, monkeypatch):
    df = pd.DataFrame({"Close": np.linspace(100, 140, 25)}, index=pd.date_range("2026-01-01", periods=25, freq="h"))
    monkeypatch.setattr(sm, "_consider_auto_retrain", lambda: None)
    monkeypatch.setattr(sm, "_build_daily_context", lambda symbol, asset_class: {ts.date(): {"d_bullish": True, "h4_bullish": True, "d_bearish": False, "h4_bearish": False, "vix_crisis": False, "vix_risk_off": False, "vix": 12} for ts in df.index})
    monkeypatch.setattr(sm, "extract_features", lambda *args, **kwargs: {col: 1.0 for col in sm.FEATURE_COLS})
    monkeypatch.setattr(sm, "predict_win_probability", lambda features: {"win_probability": 0.82, "direction": "BUY", "win_pct": 82.0})
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.technical_engine",
        SimpleNamespace(get_smart_money_analysis=lambda frame: {"structure": "bullish"}),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.risk_manager",
        SimpleNamespace(full_risk_check=lambda **kwargs: {"ok": True, "blocked_by": []}),
    )

    trainer = SimpleNamespace(predict=lambda seq_arr: (0.9, [0.2, 0.3, 0.5]))
    monkeypatch.setattr(sm, "TORCH_AVAILABLE", True)
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.neural_optimizer",
        SimpleNamespace(get_neural_trainer=lambda input_size: trainer),
    )

    aligned = sm.predict_with_neural_consensus(df, 20, side="BUY", symbol="BTCUSD", asset_class="CRYPTO")
    assert aligned["hybrid_active"] is True
    assert aligned["neural_alignment"] is True
    assert aligned["v8_prob"] == 0.9
    assert aligned["win_probability"] == 0.86

    db_path = tmp_path / "auto_retrain.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE paper_trades (outcome TEXT, status TEXT, closed_at TEXT)")
        rows = [("WIN", "CLOSED", f"2026-01-{i:02d}") for i in range(1, 11)] + [("LOSS", "CLOSED", f"2026-02-{i:02d}") for i in range(1, 16)]
        conn.executemany("INSERT INTO paper_trades VALUES (?, ?, ?)", rows)
        conn.commit()

    monkeypatch.setattr(sm, "PAPER_DB_PATH", str(db_path))
    status = sm.get_auto_retrain_status({"trained_at": "2025-01-01T00:00:00+00:00", "outcomes_at_retrain": 0})
    assert status["available"] is True
    assert status["recommended"] is True
    assert "model_age" in status["reasons"]
    assert "performance_decay" in status["reasons"]
    assert "new_labels" in status["reasons"]


def test_consider_auto_retrain_runs_worker_and_skips_when_not_needed(monkeypatch):
    monkeypatch.setattr(sm, "_LAST_AUTO_RETRAIN_CHECK", 0)
    monkeypatch.setattr("time.time", lambda: 10_000.0)

    monkeypatch.setattr(sm, "get_auto_retrain_status", lambda bundle=None: {"available": False, "recommended": False})
    sm._consider_auto_retrain()

    monkeypatch.setattr(
        sm,
        "get_auto_retrain_status",
        lambda bundle=None: {"available": True, "recommended": True, "reasons": ["model_age"], "model_age_days": 8.0},
    )
    monkeypatch.setattr(sm, "_LAST_AUTO_RETRAIN_CHECK", 0)
    sm._consider_auto_retrain()

    calls = []
    monkeypatch.setattr(
        sm,
        "get_auto_retrain_status",
        lambda bundle=None: {"available": True, "recommended": True, "reasons": ["new_labels"], "model_age_days": 1.0},
    )
    monkeypatch.setattr(sm, "_cached_dataset_with_fresh_paper_labels", lambda: pd.DataFrame([{"x": 1}]))
    monkeypatch.setattr(sm, "train_model", lambda dataset=None: calls.append(dataset is not None) or {"accuracy": 0.7, "roc_auc": 0.8, "n_samples": 100})
    monkeypatch.setattr(sm, "invalidate_model_cache", lambda: calls.append("invalidated"))

    class ImmediateThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("threading.Thread", ImmediateThread)
    monkeypatch.setattr(sm, "_LAST_AUTO_RETRAIN_CHECK", 0)
    sm._AUTO_RETRAIN_RUNNING = False
    sm._consider_auto_retrain()

    assert calls == [True, "invalidated"]


def test_train_model_rejected_by_promotion_gate(tmp_path, monkeypatch):
    model_path = tmp_path / "model.pkl"
    paper_db = tmp_path / "paper.db"
    with sqlite3.connect(paper_db) as conn:
        conn.execute("CREATE TABLE paper_trades (outcome TEXT, status TEXT)")
        conn.commit()

    rows = []
    for i in range(80):
        row = _feature_row(
            rsi=35 + (i % 20),
            adx=20 + (i % 10),
            atr_pct=0.8 + (i % 5) * 0.1,
            bb_pct=0.3 + (i % 4) * 0.1,
            vol_ratio=1.0 + (i % 3) * 0.2,
        )
        row.update(
            {
                "label": 1 if i % 2 == 0 else 0,
                "symbol": "BTCUSD" if i % 3 else "ETHUSD",
                "timeframe": "1h",
                "signal_time": pd.Timestamp("2026-01-01") + pd.Timedelta(hours=i),
                "_symbol_order": i % 2,
                "_bar_pos": i,
            }
        )
        rows.append(row)
    dataset = pd.DataFrame(rows)

    monkeypatch.setattr(sm, "MODEL_PATH", model_path)
    monkeypatch.setattr(sm, "PAPER_DB_PATH", paper_db)
    monkeypatch.setattr(sm, "TORCH_AVAILABLE", False)
    monkeypatch.setattr(sm, "_prune_weak_slices", lambda dataset, min_samples=30, min_wins=6, min_losses=6: (dataset, []))
    monkeypatch.setattr(sm, "_walk_forward_evaluate", lambda model, X, y: {"available": True, "folds": [], "summary": {"avg_accuracy": 0.51, "avg_roc_auc": 0.52}})
    monkeypatch.setattr(sm, "get_paper_label_quality_report", lambda force_refresh=False: {"available": True, "included": 0})
    monkeypatch.setattr(sm, "_build_dataset_report", lambda dataset: [{"symbol": "BTCUSD", "rows": len(dataset)}])
    monkeypatch.setattr(sm, "_build_sufficiency_status", lambda dataset, outcomes_count, dataset_report: {"ready_for_improvement": True})
    monkeypatch.setattr(sm, "_model_promotion_gate", lambda acc, auc, walk_forward: {"promote": False, "blockers": ["auc_regression"]})

    result = sm.train_model(dataset=dataset)

    assert result["status"] == "rejected"
    assert result["reason"] == "promotion_gate_failed"
    assert result["promotion_gate"]["blockers"] == ["auc_regression"]
    assert model_path.exists() is False


def test_train_model_success_writes_bundle_and_stats(tmp_path, monkeypatch):
    model_path = tmp_path / "model.pkl"
    paper_db = tmp_path / "paper.db"
    with sqlite3.connect(paper_db) as conn:
        conn.execute("CREATE TABLE paper_trades (outcome TEXT, status TEXT)")
        conn.executemany(
            "INSERT INTO paper_trades VALUES (?, ?)",
            [("WIN", "CLOSED"), ("LOSS", "CLOSED"), ("WIN", "CLOSED")],
        )
        conn.commit()

    rows = []
    for i in range(120):
        bullish = i % 2 == 0
        row = _feature_row(
            rsi=62 if bullish else 38,
            adx=32 if bullish else 18,
            atr_pct=0.9 + (i % 4) * 0.05,
            bb_pct=0.7 if bullish else 0.2,
            vol_ratio=1.6 if bullish else 0.8,
            price_vs_ema20=1.0 if bullish else -1.0,
            price_vs_ema50=1.0 if bullish else -1.0,
            bullish_align=1.0 if bullish else 0.0,
            bearish_align=0.0 if bullish else 1.0,
            macd_hist_norm=0.8 if bullish else -0.8,
            sentiment_score=0.4 if bullish else -0.4,
        )
        row.update(
            {
                "label": 1 if bullish else 0,
                "symbol": "BTCUSD" if i % 3 else "ETHUSD",
                "timeframe": "1h",
                "signal_time": pd.Timestamp("2026-02-01") + pd.Timedelta(hours=i),
                "_symbol_order": i % 2,
                "_bar_pos": i,
            }
        )
        rows.append(row)
    dataset = pd.DataFrame(rows)

    monkeypatch.setattr(sm, "MODEL_PATH", model_path)
    monkeypatch.setattr(sm, "PAPER_DB_PATH", paper_db)
    monkeypatch.setattr(sm, "TORCH_AVAILABLE", False)
    monkeypatch.setattr(sm, "_prune_weak_slices", lambda dataset, min_samples=30, min_wins=6, min_losses=6: (dataset, [{"slice": "thin", "reason": "example"}]))
    monkeypatch.setattr(
        sm,
        "_walk_forward_evaluate",
        lambda model, X, y: {"available": True, "folds": [{"accuracy": 0.7, "roc_auc": 0.74}], "summary": {"avg_accuracy": 0.7, "avg_roc_auc": 0.74}},
    )
    monkeypatch.setattr(sm, "get_paper_label_quality_report", lambda force_refresh=False: {"available": True, "included": 3})
    monkeypatch.setattr(sm, "_build_dataset_report", lambda dataset: [{"symbol": "BTCUSD", "rows": len(dataset), "win_rate": 0.5}])
    monkeypatch.setattr(sm, "_build_sufficiency_status", lambda dataset, outcomes_count, dataset_report: {"ready_for_improvement": True, "outcomes": outcomes_count})
    monkeypatch.setattr(sm, "_model_promotion_gate", lambda acc, auc, walk_forward: {"promote": True, "blockers": []})

    baseline_updates = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "intelligence.ml.drift_monitor",
        SimpleNamespace(update_baseline=lambda stats: baseline_updates.append(stats)),
    )

    result = sm.train_model(dataset=dataset)

    assert result["status"] == "trained"
    assert result["n_samples"] == len(dataset)
    assert result["pruned_slices"] == 1
    assert model_path.exists() is True
    assert baseline_updates

    with open(model_path, "rb") as fh:
        bundle = pickle.load(fh)

    assert bundle["promotion_gate"]["promote"] is True
    assert bundle["paper_label_quality"]["included"] == 3
    assert bundle["sufficiency"]["ready_for_improvement"] is True
    assert bundle["train_size"] > 0
    assert bundle["test_size"] > 0
