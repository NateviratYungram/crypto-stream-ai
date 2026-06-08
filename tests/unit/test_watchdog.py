import json
import sys
from pathlib import Path
from types import SimpleNamespace

from intelligence.ml import watchdog


def test_build_watchdog_report_flags_stale_assets(tmp_path, monkeypatch):
    now_ts = 1_700_000_000
    model_path = tmp_path / "signal_model.pkl"
    model_path.write_text("model", encoding="utf-8")
    ops_dir = tmp_path / "reports"
    ops_dir.mkdir()
    ops_report = ops_dir / "ml_ops_report.json"
    ops_report.write_text("{}", encoding="utf-8")

    stale_model_ts = now_ts - (80 * 3600)
    stale_ops_ts = now_ts - (8 * 3600)
    model_path.touch()
    ops_report.touch()
    import os
    os.utime(model_path, (stale_model_ts, stale_model_ts))
    os.utime(ops_report, (stale_ops_ts, stale_ops_ts))

    fake_readiness = SimpleNamespace(
        evaluate_readiness=lambda require_mt5_audit=False: {
            "passed": False,
            "blockers": [{"name": "paper_label_count"}],
        }
    )
    fake_reporting = SimpleNamespace(
        build_promotion_summary=lambda limit=5: {
            "latest": {"status": "trained", "roc_auc": 0.61, "accuracy": 0.57, "walk_forward_auc": 0.55}
        }
    )
    fake_signal_model = SimpleNamespace(MODEL_PATH=model_path)

    monkeypatch.setitem(sys.modules, "intelligence.ml.readiness", fake_readiness)
    monkeypatch.setitem(sys.modules, "intelligence.ml.reporting", fake_reporting)
    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", fake_signal_model)
    monkeypatch.setenv("ML_OPS_REPORT_DIR", str(ops_dir))

    class FrozenDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, timezone

            return datetime.fromtimestamp(now_ts, tz=timezone.utc)

        @staticmethod
        def fromtimestamp(value, tz=None):
            from datetime import datetime

            return datetime.fromtimestamp(value, tz=tz)

    monkeypatch.setattr(watchdog, "datetime", FrozenDateTime)

    report = watchdog.build_watchdog_report()

    assert report["healthy"] is False
    assert "model file older than 72h" in report["warnings"][0]
    assert any("ops report older than 6h" in warning for warning in report["warnings"])
    assert "live readiness still blocked" in report["warnings"]
    assert report["model"]["exists"] is True
    assert report["ops_report"]["exists"] is True
    assert report["latest_promotion"]["roc_auc"] == 0.61


def test_write_watchdog_report_persists_json(tmp_path, monkeypatch):
    target_dir = tmp_path / "watchdog"
    monkeypatch.setenv("ML_OPS_REPORT_DIR", str(target_dir))
    monkeypatch.setattr(
        watchdog,
        "build_watchdog_report",
        lambda: {"healthy": True, "warnings": [], "generated_at": "2026-05-25T00:00:00+00:00"},
    )

    output = watchdog.write_watchdog_report()

    assert output == Path(target_dir) / "ml_watchdog_report.json"
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["healthy"] is True


def test_build_watchdog_report_when_assets_missing_and_no_blockers(tmp_path, monkeypatch):
    ops_dir = tmp_path / "missing-reports"

    fake_readiness = SimpleNamespace(
        evaluate_readiness=lambda require_mt5_audit=False: {
            "passed": False,
            "blockers": [],
        }
    )
    fake_reporting = SimpleNamespace(build_promotion_summary=lambda limit=5: {"latest": None})
    fake_signal_model = SimpleNamespace(MODEL_PATH=tmp_path / "missing-model.pkl")

    monkeypatch.setitem(sys.modules, "intelligence.ml.readiness", fake_readiness)
    monkeypatch.setitem(sys.modules, "intelligence.ml.reporting", fake_reporting)
    monkeypatch.setitem(sys.modules, "intelligence.ml.signal_model", fake_signal_model)
    monkeypatch.setenv("ML_OPS_REPORT_DIR", str(ops_dir))

    class FrozenDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, timezone

            return datetime(2026, 6, 3, tzinfo=timezone.utc)

        @staticmethod
        def fromtimestamp(value, tz=None):
            from datetime import datetime

            return datetime.fromtimestamp(value, tz=tz)

    monkeypatch.setattr(watchdog, "datetime", FrozenDateTime)

    report = watchdog.build_watchdog_report()

    assert report["healthy"] is True
    assert report["warnings"] == []
    assert report["model"] == {"exists": False, "age_hours": None}
    assert report["ops_report"]["exists"] is False
    assert report["ops_report"]["age_hours"] is None
    assert report["latest_promotion"] == {
        "status": None,
        "roc_auc": None,
        "accuracy": None,
        "walk_forward_auc": None,
    }
