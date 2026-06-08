import logging
import sys
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.append(str(Path.cwd()))

from intelligence.ml.neural_optimizer import get_neural_trainer
from intelligence.ml.signal_model import (
    build_ml_dataset,
    get_paper_label_quality_report,
    invalidate_model_cache,
    train_model,
)
from intelligence.ml.symbol_threshold import refresh_threshold_cache
from intelligence.ml.trading_quality_gate import clear_trading_quality_gate_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("V8Trainer")


def _finalize_caches() -> None:
    invalidate_model_cache()
    refresh_threshold_cache()
    clear_trading_quality_gate_cache()


def train(limit: int = 500000, neural_epochs: int = 150) -> dict:
    logger.info("Starting Intelligence V8 training cycle")
    logger.info("Data source: PostgreSQL + paper outcomes")

    logger.info("--- Phase 0: Dataset Build ---")
    dataset = build_ml_dataset(limit=limit)
    if dataset.empty:
        logger.error("Failed to build dataset. Check DB connection and data availability.")
        return {"status": "error", "reason": "dataset_empty"}

    paper_quality = get_paper_label_quality_report(force_refresh=True)
    logger.info(
        "[PaperLabels] included=%s excluded=%s reasons=%s",
        paper_quality.get("included"),
        paper_quality.get("excluded"),
        paper_quality.get("reasons", {}),
    )

    logger.info("--- Phase 1: Ensemble Training ---")
    ensemble_results = train_model(dataset=dataset)
    if "error" in ensemble_results:
        logger.error("Ensemble failed: %s", ensemble_results["error"])
        return {"status": "error", "reason": ensemble_results["error"], "paper_label_quality": paper_quality}

    if ensemble_results.get("status") == "rejected":
        logger.warning(
            "Ensemble promotion rejected | blockers=%s",
            (ensemble_results.get("promotion_gate") or {}).get("blockers", []),
        )
        clear_trading_quality_gate_cache()
        return {**ensemble_results, "paper_label_quality": paper_quality}

    logger.info(
        "Ensemble trained | acc=%.4f auc=%.4f samples=%s",
        float(ensemble_results.get("accuracy", 0.0) or 0.0),
        float(ensemble_results.get("roc_auc", 0.0) or 0.0),
        ensemble_results.get("n_samples"),
    )

    if "_sequence" not in dataset.columns:
        logger.warning("No sequence column available - skipping neural phase")
        _finalize_caches()
        return {
            "status": "trained",
            "ensemble": ensemble_results,
            "neural": {"status": "skipped", "reason": "no_sequence_column"},
            "paper_label_quality": paper_quality,
        }

    logger.info("--- Phase 2: Neural Sequence Preparation ---")
    raw = dataset[dataset["_sequence"].notna()].copy()
    seq_list = raw["_sequence"].tolist()
    y_raw = raw["label"].values.astype(np.float32)

    ref_shape = None
    good_seqs, good_y = [], []
    for seq, lbl in zip(seq_list, y_raw):
        try:
            arr = np.array(seq, dtype=np.float32)
            if ref_shape is None and arr.ndim == 2:
                ref_shape = arr.shape
            if arr.shape == ref_shape:
                good_seqs.append(arr)
                good_y.append(lbl)
        except Exception:
            continue

    if not good_seqs:
        logger.warning("No valid sequences after filtering - skipping neural phase")
        _finalize_caches()
        return {
            "status": "trained",
            "ensemble": ensemble_results,
            "neural": {"status": "skipped", "reason": "no_valid_sequences"},
            "paper_label_quality": paper_quality,
        }

    X = np.stack(good_seqs)
    y = np.array(good_y, dtype=np.float32)
    logger.info("Prepared %s sequences of shape %s", len(X), list(X.shape[1:]))

    logger.info("--- Phase 3: Neural Training ---")
    trainer = get_neural_trainer(input_size=int(X.shape[-1]))
    neural_summary = {"status": "skipped", "reason": "trainer_unavailable"}
    if trainer:
        val_loss = trainer.train_on_sequences(X, y, epochs=neural_epochs)
        logger.info("Neural training complete | val_loss=%.4f", float(val_loss))
        neural_summary = {
            "status": "trained",
            "val_loss": float(val_loss),
            "sequence_count": int(len(X)),
            "sequence_shape": list(X.shape[1:]),
        }
    else:
        logger.warning("Neural trainer not available")

    _finalize_caches()
    logger.info("Intelligence V8 training cycle complete")
    return {
        "status": "trained",
        "ensemble": ensemble_results,
        "neural": neural_summary,
        "paper_label_quality": paper_quality,
    }


def main():
    train()


if __name__ == "__main__":
    main()
