
import logging
import sys
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.append(str(Path.cwd()))

from intelligence.ml.neural_optimizer import get_neural_trainer
from intelligence.ml.signal_model import build_ml_dataset, train_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("V8Trainer")

def main():
    logger.info("🚀 Starting Intelligence V8: Clinical Precision Training Cycle")
    logger.info("   [Data Source: PostgreSQL 10-Year Big Data]")
    logger.info("   [Asymmetric Risk-Aware Loss Active: FP Penalty = 3x]")

    # 1. Build common dataset for all models
    logger.info("--- Phase 0: Big Data Acquisition & Sequence Synthesis ---")
    dataset = build_ml_dataset(limit=500000) # Full historical lookback

    if dataset.empty:
        logger.error("❌ Failed to build dataset. Check DB connection and data availability.")
        return

    # 2. Train Ensemble V8 (GBM/RF with Fractal Features)
    logger.info("--- Phase 1: Ensemble V8 Hardening ---")
    ensemble_results = train_model(dataset=dataset)
    if "error" in ensemble_results:
        logger.error(f"Ensemble failed: {ensemble_results['error']}")
    else:
        logger.info(f"✅ Ensemble Accuracy: {ensemble_results.get('accuracy', 0):.4f} | AUC: {ensemble_results.get('roc_auc', 0):.4f} | Samples: {ensemble_results.get('n_samples')}")

    # 3. Prepare neural training sequences
    logger.info("--- Phase 2: Neural Sequence Preparation ---")
    if "_sequence" not in dataset.columns:
        logger.warning("No sequence data available - skipping Neural retrain")
        logger.info("✅ Intelligence V8 Ensemble Cycle Complete.")
        return

    X = np.array(dataset["_sequence"].tolist(), dtype=np.float32)
    y = dataset["label"].values.astype(np.float32)
    logger.info(f"Synthesized {len(X)} sequences for Deep Brain training.")

    # 4. Train Neural V8 (Attention-GRU with Asymmetric Risk-Aware Loss)
    logger.info("--- Phase 3: Neural V8 Clinical Hardening (Sniper Precision Mode) ---")
    trainer = get_neural_trainer()
    if trainer:
        val_loss = trainer.train_on_sequences(X, y, epochs=150)
        logger.info(f"✅ Neural Training Complete. Final Val Loss: {val_loss:.4f}")
    else:
        logger.warning("Neural Trainer not available (Torch missing?)")

    logger.info("🏆 Intelligence V8 Clinical Precision Evolution Complete!")

if __name__ == "__main__":
    main()
