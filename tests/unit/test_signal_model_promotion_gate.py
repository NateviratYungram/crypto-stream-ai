from intelligence.ml import signal_model


def test_model_promotion_gate_allows_small_accuracy_shortfall_when_auc_improves(monkeypatch):
    monkeypatch.setattr(signal_model, "MODEL_PATH", signal_model.MODEL_PATH)
    monkeypatch.setattr(
        signal_model,
        "_load_model",
        lambda: {
            "accuracy": 0.3788,
            "roc_auc": 0.5117,
            "walk_forward": {"summary": {"avg_roc_auc": 0.505}},
        },
    )

    gate = signal_model._model_promotion_gate(
        acc=0.3488,
        auc=0.5204,
        walk_forward={"summary": {"avg_roc_auc": 0.507}},
    )

    assert gate["promote"] is True
    assert gate["blockers"] == []
    assert "accuracy override" in gate["override_reason"]
