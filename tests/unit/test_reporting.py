from pathlib import Path

from intelligence.ml import reporting


def test_build_promotion_summary_when_empty(tmp_path, monkeypatch):
    db_path = tmp_path / "persistence.db"
    monkeypatch.setattr(reporting, "PROMOTION_DB", Path(db_path))

    summary = reporting.build_promotion_summary(limit=0)

    assert summary == {
        "available": False,
        "count": 0,
        "trained_count": 0,
        "rejected_count": 0,
        "latest": None,
        "history": [],
    }


def test_record_and_read_promotion_history(tmp_path, monkeypatch):
    db_path = tmp_path / "persistence.db"
    monkeypatch.setattr(reporting, "PROMOTION_DB", Path(db_path))

    result = {
        "status": "trained",
        "accuracy": 0.35,
        "roc_auc": 0.52,
        "n_samples": 1234,
        "paper_label_quality": {"included": 10},
        "walk_forward": {"summary": {"avg_roc_auc": 0.51}},
        "promotion_gate": {"override_reason": "auc improved", "blockers": []},
    }
    reporting.record_promotion_event(result, "unit_test")
    summary = reporting.build_promotion_summary(limit=5)

    assert summary["available"] is True
    assert summary["count"] == 1
    assert summary["latest"]["trigger_reason"] == "unit_test"
    assert summary["latest"]["roc_auc"] == 0.52


def test_get_promotion_history_clamps_limit_and_falls_back_for_invalid_json(tmp_path, monkeypatch):
    db_path = tmp_path / "persistence.db"
    monkeypatch.setattr(reporting, "PROMOTION_DB", Path(db_path))
    reporting.ensure_reporting_tables()

    with reporting._connect() as conn:
        conn.execute(
            """
            INSERT INTO ml_promotion_history (
                trigger_reason, status, reason, accuracy, roc_auc, walk_forward_auc,
                n_samples, trained_at, override_reason, blockers_json,
                paper_label_quality_json, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "manual",
                "rejected",
                "bad json",
                None,
                None,
                None,
                0,
                "2026-01-01T00:00:00+00:00",
                None,
                "{invalid",
                '{"included": 1}',
                '{"status": "rejected"}',
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO ml_promotion_history (
                trigger_reason, status, reason, accuracy, roc_auc, walk_forward_auc,
                n_samples, trained_at, override_reason, blockers_json,
                paper_label_quality_json, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "newer",
                "trained",
                "ok",
                0.6,
                0.7,
                0.8,
                5,
                "2026-01-02T00:00:00+00:00",
                "override",
                '["none"]',
                '{"included": 2}',
                '{"status": "trained"}',
                "2026-01-02T00:00:00+00:00",
            ),
        )
        conn.commit()

    history = reporting.get_promotion_history(limit=999)

    assert len(history) == 2
    assert history[0]["trigger_reason"] == "newer"
    assert history[0]["blockers"] == ["none"]
    assert history[1]["blockers"] == "{invalid"
    assert history[1]["paper_label_quality"] == {"included": 1}
    assert history[1]["result"] == {"status": "rejected"}
