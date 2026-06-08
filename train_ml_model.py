#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick CLI to train the ML signal model without needing Airflow.

Usage:
  python train_ml_model.py              # default symbols, 5000 bars each
  python train_ml_model.py --limit 500  # faster, fewer bars
  python train_ml_model.py --scan       # scan paper trade outcomes first
  python train_ml_model.py --readiness  # show live-trading readiness report
"""
import argparse
import logging
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="Train CryptoStream AI signal model")
    parser.add_argument("--limit", type=int, default=5000, help="Bars per symbol (default: 5000)")
    parser.add_argument("--scan", action="store_true", help="Scan paper trade outcomes first")
    parser.add_argument("--stats", action="store_true", help="Show paper trade stats and exit")
    parser.add_argument("--readiness", action="store_true", help="Show ML live-trading readiness report and exit")
    parser.add_argument("--mt5-audit", action="store_true", help="Include MT5 broker history audit in readiness")
    parser.add_argument("--use-mt5", action="store_true", help="Prefer MT5 broker history during training")
    args = parser.parse_args()

    if args.use_mt5:
        os.environ["ML_TRAIN_USE_MT5"] = "1"

    if args.readiness:
        from intelligence.ml.readiness import evaluate_readiness, print_readiness_json

        print_readiness_json(evaluate_readiness(require_mt5_audit=args.mt5_audit))
        return

    if args.stats:
        from intelligence.ml.outcome_tracker import get_ml_stats

        stats = get_ml_stats()
        print("\nPaper Trade ML Stats:")
        print(f"   Total labeled trades : {stats['total_labeled']}")
        print(f"   Wins                 : {stats['wins']}")
        print(f"   Losses               : {stats['losses']}")
        wr = stats.get("win_rate")
        print(f"   Win rate             : {f'{wr:.1%}' if wr is not None else 'N/A (no data yet)'}")
        return

    if args.scan:
        print("Scanning paper trade outcomes...")
        from intelligence.ml.outcome_tracker import scan_and_update

        summary = scan_and_update()
        print(f"   Scanned     : {summary['scanned']} open trades")
        print(f"   Closed WIN  : {summary['closed_win']}")
        print(f"   Closed LOSS : {summary['closed_loss']}")
        print()

    print(f"Training signal model (limit={args.limit} bars/symbol)...")
    from intelligence.ml.signal_model import invalidate_model_cache, train_model

    result = train_model(limit=args.limit)

    if "error" in result:
        print(f"\nTraining failed: {result['error']}")
        sys.exit(1)

    invalidate_model_cache()
    print("\nModel trained successfully.")
    print(f"   Samples   : {result['n_samples']:,}")
    print(f"   Accuracy  : {result['accuracy']:.1%}")
    print(f"   ROC AUC   : {result['roc_auc']:.3f}")
    print(f"   Win rate  : {result['win_rate']:.1%}")
    print(f"   Saved to  : {result['model_path']}")
    print("\nThe AI will now show ML Edge Scores on every analysis request.")


if __name__ == "__main__":
    main()
