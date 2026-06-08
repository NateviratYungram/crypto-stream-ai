from intelligence.ml import train_v8


def test_train_v8_exposes_train_callable():
    assert callable(train_v8.train)


def test_train_returns_error_when_dataset_is_empty(monkeypatch):
    class EmptyDataset:
        empty = True

    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: EmptyDataset())

    result = train_v8.train()

    assert result == {"status": "error", "reason": "dataset_empty"}


def test_train_returns_error_when_ensemble_training_fails(monkeypatch):
    class Dataset:
        empty = False

    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: Dataset())
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 1, "excluded": 2, "reasons": {"small_pnl": 2}})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"error": "db_down"})

    result = train_v8.train()

    assert result["status"] == "error"
    assert result["reason"] == "db_down"
    assert result["paper_label_quality"]["included"] == 1


def test_train_returns_rejected_results_and_clears_gate_cache(monkeypatch):
    class Dataset:
        empty = False

    cleared = {"called": False}
    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: Dataset())
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 3})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"status": "rejected", "promotion_gate": {"blockers": ["auc"]}})
    monkeypatch.setattr(train_v8, "clear_trading_quality_gate_cache", lambda: cleared.update({"called": True}))

    result = train_v8.train()

    assert result["status"] == "rejected"
    assert result["paper_label_quality"]["included"] == 3
    assert cleared["called"] is True


def test_train_skips_neural_phase_without_sequence_column(monkeypatch):
    class Dataset:
        empty = False
        columns = ["label"]

    finalized = {"called": False}
    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: Dataset())
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 4})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"status": "trained", "accuracy": 0.6, "roc_auc": 0.7, "n_samples": 100})
    monkeypatch.setattr(train_v8, "_finalize_caches", lambda: finalized.update({"called": True}))

    result = train_v8.train()

    assert result["status"] == "trained"
    assert result["neural"]["reason"] == "no_sequence_column"
    assert finalized["called"] is True


def test_train_skips_neural_phase_when_no_valid_sequences(monkeypatch):
    class FakeSeries:
        def __init__(self, values):
            self.values = values

        def notna(self):
            return [True for _ in self.values]

        def tolist(self):
            return list(self.values)

        @property
        def values(self):
            return self._values

        @values.setter
        def values(self, value):
            self._values = value

    class FakeArrayValues:
        def __init__(self, values):
            self._values = values

        def astype(self, dtype):
            return self._values

    class FakeFilteredDataset:
        def __init__(self):
            self.columns = ["_sequence", "label"]

        def copy(self):
            return self

        def __getitem__(self, key):
            if key == "_sequence":
                return FakeSeries([123, 456])
            if key == "label":
                return SimpleNamespace(values=FakeArrayValues([1.0, 0.0]))
            if isinstance(key, list):
                return self
            raise KeyError(key)

    class FakeDataset(FakeFilteredDataset):
        empty = False

    from types import SimpleNamespace

    finalized = {"called": False}
    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: FakeDataset())
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 5})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"status": "trained", "accuracy": 0.6, "roc_auc": 0.7, "n_samples": 100})
    monkeypatch.setattr(train_v8, "_finalize_caches", lambda: finalized.update({"called": True}))

    result = train_v8.train()

    assert result["neural"]["reason"] == "no_valid_sequences"
    assert finalized["called"] is True


def test_train_completes_with_trainer_summary(monkeypatch):
    class FakeSeries:
        def __init__(self, values):
            self._values = values

        def notna(self):
            return [True for _ in self._values]

        def tolist(self):
            return list(self._values)

    class FakeArrayValues:
        def __init__(self, values):
            self._values = values

        def astype(self, dtype):
            return self._values

    class FakeFilteredDataset:
        def __init__(self, sequences, labels):
            self.sequences = sequences
            self.labels = labels
            self.columns = ["_sequence", "label"]

        def copy(self):
            return self

        def __getitem__(self, key):
            if key == "_sequence":
                return FakeSeries(self.sequences)
            if key == "label":
                return SimpleNamespace(values=FakeArrayValues(self.labels))
            if isinstance(key, list):
                return self
            raise KeyError(key)

    class FakeDataset(FakeFilteredDataset):
        empty = False

    from types import SimpleNamespace

    trainer_calls = {}
    finalized = {"called": False}

    class FakeTrainer:
        def train_on_sequences(self, X, y, epochs):
            trainer_calls["shape"] = X.shape
            trainer_calls["y"] = list(y)
            trainer_calls["epochs"] = epochs
            return 0.1234

    monkeypatch.setattr(
        train_v8,
        "build_ml_dataset",
        lambda limit=500000: FakeDataset(
            sequences=[[[1.0, 2.0], [3.0, 4.0]], [[2.0, 3.0], [4.0, 5.0]]],
            labels=[1.0, 0.0],
        ),
    )
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 8})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"status": "trained", "accuracy": 0.6, "roc_auc": 0.7, "n_samples": 100})
    monkeypatch.setattr(train_v8, "get_neural_trainer", lambda input_size: FakeTrainer())
    monkeypatch.setattr(train_v8, "_finalize_caches", lambda: finalized.update({"called": True}))

    result = train_v8.train(neural_epochs=9)

    assert result["status"] == "trained"
    assert result["neural"]["status"] == "trained"
    assert result["neural"]["val_loss"] == 0.1234
    assert result["neural"]["sequence_count"] == 2
    assert result["neural"]["sequence_shape"] == [2, 2]
    assert trainer_calls["shape"] == (2, 2, 2)
    assert trainer_calls["epochs"] == 9
    assert finalized["called"] is True


def test_finalize_caches_calls_all_invalidation_hooks(monkeypatch):
    calls = []
    monkeypatch.setattr(train_v8, "invalidate_model_cache", lambda: calls.append("model"))
    monkeypatch.setattr(train_v8, "refresh_threshold_cache", lambda: calls.append("threshold"))
    monkeypatch.setattr(train_v8, "clear_trading_quality_gate_cache", lambda: calls.append("quality_gate"))

    train_v8._finalize_caches()

    assert calls == ["model", "threshold", "quality_gate"]


def test_train_marks_neural_phase_skipped_when_trainer_is_unavailable(monkeypatch):
    class FakeSeries:
        def __init__(self, values):
            self._values = values

        def notna(self):
            return [True for _ in self._values]

        def tolist(self):
            return list(self._values)

    class FakeArrayValues:
        def __init__(self, values):
            self._values = values

        def astype(self, dtype):
            return self._values

    class FakeFilteredDataset:
        columns = ["_sequence", "label"]

        def copy(self):
            return self

        def __getitem__(self, key):
            if key == "_sequence":
                return FakeSeries([[[1.0, 2.0], [3.0, 4.0]]])
            if key == "label":
                from types import SimpleNamespace
                return SimpleNamespace(values=FakeArrayValues([1.0]))
            if isinstance(key, list):
                return self
            raise KeyError(key)

    class FakeDataset(FakeFilteredDataset):
        empty = False

    finalized = {"called": False}
    monkeypatch.setattr(train_v8, "build_ml_dataset", lambda limit=500000: FakeDataset())
    monkeypatch.setattr(train_v8, "get_paper_label_quality_report", lambda force_refresh=True: {"included": 9})
    monkeypatch.setattr(train_v8, "train_model", lambda dataset=None: {"status": "trained", "accuracy": 0.7, "roc_auc": 0.8, "n_samples": 111})
    monkeypatch.setattr(train_v8, "get_neural_trainer", lambda input_size: None)
    monkeypatch.setattr(train_v8, "_finalize_caches", lambda: finalized.update({"called": True}))

    result = train_v8.train()

    assert result["neural"] == {"status": "skipped", "reason": "trainer_unavailable"}
    assert finalized["called"] is True


def test_main_delegates_to_train(monkeypatch):
    called = {"count": 0}
    monkeypatch.setattr(train_v8, "train", lambda: called.update({"count": called["count"] + 1}) or {"status": "trained"})

    assert train_v8.main() is None
    assert called["count"] == 1
