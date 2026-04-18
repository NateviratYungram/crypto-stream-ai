
import sys
import os
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

from intelligence.ml.signal_model import train_model, build_ml_dataset
from intelligence.ml.neural_optimizer import get_neural_trainer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("V8Trainer")

def main():
    logger.info("🚀 Starting Intelligence V8: Clinical Precision Training Cycle")
    logger.info("   [Asymmetric Risk-Aware Loss Active: FP Penalty = 3x]")
    
    # 1. Train Ensemble V8 (GBM/RF with Fractal Features)
    logger.info("--- Phase 1: Ensemble V8 Hardening ---")
    ensemble_results = train_model()
    if "error" in ensemble_results:
        logger.error(f"Ensemble failed: {ensemble_results['error']}")
        return
    logger.info(f"✅ Ensemble Accuracy: {ensemble_results.get('accuracy', 0):.4f} | AUC: {ensemble_results.get('roc_auc', 0):.4f} | Samples: {ensemble_results.get('n_samples')}")
    
    # 2. Build and prepare neural training sequences from same dataset
    logger.info("--- Phase 2: Neural Sequence Synthesis ---")
    dataset = build_ml_dataset()
    if dataset.empty or "_sequence" not in dataset.columns:
        logger.warning("No sequence data available - skipping Neural retrain")
        logger.info("✅ Intelligence V8 Ensemble Cycle Complete.")
        return

    X = np.array(dataset["_sequence"].tolist(), dtype=np.float32)
    y = dataset["label"].values.astype(np.float32)
    logger.info(f"Synthesized {len(X)} sequences for Deep Brain training.")
    
    # 3. Train Neural V8 (Attention-GRU with Asymmetric Risk-Aware Loss)
    logger.info("--- Phase 3: Neural V8 Clinical Hardening (Sniper Precision Mode) ---")
    trainer = get_neural_trainer()
    val_loss = trainer.train_on_sequences(X, y, epochs=100)
    logger.info(f"✅ Neural Training Complete. Final Val Loss: {val_loss:.4f}")
    
    logger.info("🏆 Intelligence V8 Clinical Precision Evolution Complete!")

if __name__ == "__main__":
    main()
