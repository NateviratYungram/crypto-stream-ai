import json

from intelligence.ml import drift_monitor


def test_load_baseline_reads_stats_file(tmp_path):
    stats_path = tmp_path / "training_stats.json"
    stats_path.write_text(json.dumps({"rsi": {"mean": 40.0, "std": 10.0, "weight": 1.0}}), encoding="utf-8")

    baseline = drift_monitor._load_baseline(stats_path=stats_path)

    assert baseline["rsi"]["mean"] == 40.0


def test_load_baseline_falls_back_to_default_when_file_invalid(tmp_path):
    stats_path = tmp_path / "training_stats.json"
    stats_path.write_text("{not-json}", encoding="utf-8")

    baseline = drift_monitor._load_baseline(stats_path=stats_path)

    assert baseline == drift_monitor._DEFAULT_BASELINE


def test_check_drift_tracks_history_and_status_levels():
    monitor = drift_monitor.DriftMonitor(
        baseline={
            "rsi": {"mean": 50.0, "std": 10.0, "weight": 1.0},
            "atr_pct": {"mean": 0.01, "std": 0.001, "weight": 2.0},
        },
        history_limit=2,
    )

    stable = monitor.check_drift({"rsi": 52.0, "atr_pct": 0.0105})
    warning = monitor.check_drift({"rsi": 90.0, "atr_pct": 0.02})
    critical = monitor.check_drift({"rsi": 130.0, "atr_pct": 0.05})

    assert stable["status"] == "STABLE"
    assert warning["status"] in {"WARNING", "CRITICAL_DRIFT"}
    assert critical["status"] == "CRITICAL_DRIFT"
    assert any("OUTLIER" in item for item in critical["warnings"])
    assert len(monitor.feature_history["rsi"]) == 2


def test_get_drift_report_and_update_baseline(monkeypatch):
    monitor = drift_monitor.DriftMonitor(baseline={"rsi": {"mean": 50.0, "std": 10.0, "weight": 1.0}})
    monkeypatch.setattr(drift_monitor, "drift_shield", monitor)

    report = drift_monitor.get_drift_report({"rsi": 55.0})
    drift_monitor.update_baseline({"atr_pct": {"mean": 0.01, "std": 0.002, "weight": 1.0}})

    assert report["integrity_score"] > 0
    assert "atr_pct" in drift_monitor.drift_shield.baseline
    assert drift_monitor.drift_shield.feature_history == {"atr_pct": []}
