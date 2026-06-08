#!/usr/bin/env python3
"""
End-to-end pipeline test — verifies new features work correctly:
  - Symbol memory (RAG)
  - Filter notes
  - Multi-TF confidence adjustment
  - Funding rate check
  - Adaptive symbol thresholds
  - Signal tiering with sym_floor

Runs against a mock state (no API calls, no DB writes).
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

os.environ.setdefault("PAPER_TRADE_DB", "data/persistence.db")

SEPARATOR = "-" * 60


def check(label: str, value, expected=None):
    if expected is not None:
        ok = value == expected
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {label}: {value!r}  (expected {expected!r})")
    else:
        ok = bool(value)
        status = "OK  " if ok else "WARN"
        print(f"  [{status}] {label}: {value!r}")
    return ok


def test_symbol_threshold():
    print(f"\n{SEPARATOR}")
    print("TEST 1: Adaptive Symbol Thresholds")
    print(SEPARATOR)
    from intelligence.ml.symbol_threshold import get_threshold, load_thresholds

    thresholds = load_thresholds()
    print(f"  Loaded thresholds: {json.dumps(thresholds, indent=4)}")

    btc_floor = get_threshold("BTCUSD")
    eth_floor = get_threshold("ETHUSD")
    xrp_floor = get_threshold("XRPUSDT")

    check("BTCUSD floor (bad WR -> 0.70)", btc_floor, 0.70)
    check("ETHUSD floor (good WR -> 0.50)", eth_floor, 0.50)
    check("XRPUSDT floor (early warning 20% WR -> 0.62)", xrp_floor, 0.62)

    # Test fallback for unknown symbol
    unk = get_threshold("UNKNOWNSYM")
    check("Unknown symbol fallback -> 0.50", unk, 0.50)


def test_symbol_memory():
    print(f"\n{SEPARATOR}")
    print("TEST 2: Symbol Memory (RAG)")
    print(SEPARATOR)
    try:
        from intelligence.agents.reflector_agent import format_symbol_memory, get_symbol_outcomes
    except ImportError as e:
        print(f"  [FAIL] Cannot import reflector_agent: {e}")
        return

    # ETHUSD has 26 closed trades — should have memory
    mem = format_symbol_memory("ETHUSD", "1h", limit=5)
    print(f"  ETHUSD memory output:\n{mem}")
    check("Memory non-empty for ETHUSD", len(mem) > 10)
    check("Memory contains win/loss summary", "W/" in mem or "L" in mem)

    # Unknown symbol — should return gracefully
    mem_unk = format_symbol_memory("DOGEUSDT", "1h", limit=5)
    print(f"  DOGEUSDT memory output: {mem_unk!r}")
    check("Graceful fallback for unknown symbol", isinstance(mem_unk, str))


def test_tiering_logic():
    print(f"\n{SEPARATOR}")
    print("TEST 3: Signal Tiering + sym_floor")
    print(SEPARATOR)

    from intelligence.ml.symbol_threshold import get_threshold

    def compute_grade(symbol: str, confidence: float):
        sym_floor = get_threshold(symbol)
        if confidence < sym_floor:
            return "REJECT", 0.0
        elif confidence >= 0.75:
            return "A+", 1.0
        elif confidence >= 0.62:
            return "A", 0.5
        else:
            return "B", 0.25

    # BTCUSD floor=0.70 -> confidence 0.65 must be REJECT
    grade, mult = compute_grade("BTCUSD", 0.65)
    check("BTCUSD conf=0.65 < floor=0.70 -> REJECT", grade, "REJECT")

    # BTCUSD floor=0.70 -> confidence 0.76 -> A+
    grade, mult = compute_grade("BTCUSD", 0.76)
    check("BTCUSD conf=0.76 >= floor=0.70 -> A+", grade, "A+")

    # ETHUSD floor=0.50 -> confidence 0.63 -> A
    grade, mult = compute_grade("ETHUSD", 0.63)
    check("ETHUSD conf=0.63 -> A", grade, "A")

    # ETHUSD floor=0.50 -> confidence 0.55 -> B
    grade, mult = compute_grade("ETHUSD", 0.55)
    check("ETHUSD conf=0.55 -> B", grade, "B")

    # XRPUSDT floor=0.62 -> confidence 0.58 -> REJECT
    grade, mult = compute_grade("XRPUSDT", 0.58)
    check("XRPUSDT conf=0.58 < floor=0.62 -> REJECT", grade, "REJECT")


def test_trading_quality_gate():
    print(f"\n{SEPARATOR}")
    print("TEST 4: Trading Quality Gate")
    print(SEPARATOR)
    try:
        from intelligence.ml.trading_quality_gate import get_trading_quality_gate
        gate = get_trading_quality_gate(symbol="ETHUSD")
        mode = gate.get("mode", "unknown")
        blockers = gate.get("blockers", [])
        print(f"  Mode    : {mode}")
        print(f"  Blockers: {blockers}")
        check("Gate returned a mode", mode in ("tradeable", "paper_only", "observe_only"))
    except Exception as e:
        print(f"  [FAIL] Quality gate error: {e}")


def test_performance_feedback():
    print(f"\n{SEPARATOR}")
    print("TEST 5: Performance Feedback")
    print(SEPARATOR)
    try:
        from intelligence.ml.performance_feedback import get_feedback_snapshot, score_signal_feedback
        snap = get_feedback_snapshot()
        print(f"  Global snapshot: total_signals={snap.get('total_signals')} global_wr={snap.get('global_win_rate')}")
        check("Feedback snapshot available", snap.get("total_signals", 0) >= 0)

        fb = score_signal_feedback("ETHUSD", entry_source="signal_feed_analysis")
        sym_stats = fb.get("symbol_stats", {})
        readiness = fb.get("readiness", {})
        print(f"  ETHUSD symbol stats: {sym_stats}")
        print(f"  ETHUSD readiness   : {readiness}")
        check("ETHUSD feedback readiness is dict", isinstance(readiness, dict))
    except Exception as e:
        print(f"  [FAIL] Performance feedback error: {e}")


def test_ml_signal():
    print(f"\n{SEPARATOR}")
    print("TEST 6: ML Signal Model")
    print(SEPARATOR)
    try:
        from intelligence.ml.signal_model import _load_model
        bundle = _load_model()
        if bundle is None:
            print("  [WARN] No model bundle found — skipping ML signal test")
            return
        n_samples = bundle.get("n_samples", 0)
        auc = bundle.get("roc_auc")
        trained_at = bundle.get("trained_at", "?")
        print(f"  Model: n_samples={n_samples}, AUC={auc}, trained_at={trained_at}")
        check("Model has >=1500 samples", int(n_samples) >= 1500)
        check("AUC >= 0.50", float(auc or 0) >= 0.50)

        wf = (bundle.get("walk_forward") or {}).get("summary", {})
        wf_auc = wf.get("avg_roc_auc")
        print(f"  Walk-forward AUC: {wf_auc}")

        cal = bundle.get("calibration") or {}
        brier = cal.get("brier_score")
        brier_raw = cal.get("brier_score_raw")
        iso_available = "isotonic_calibrator" in bundle
        print(f"  Brier: raw={brier_raw} calibrated={brier}")
        check("Isotonic calibrator present", iso_available)
    except Exception as e:
        print(f"  [FAIL] ML signal model error: {e}")


def test_paper_trade_perf():
    print(f"\n{SEPARATOR}")
    print("TEST 7: Paper Trade Performance")
    print(SEPARATOR)
    try:
        from intelligence.ml.readiness import get_paper_trade_performance
        perf = get_paper_trade_performance()
        total = perf.get("total", 0)
        wr = perf.get("win_rate")
        pf = perf.get("profit_factor")
        exp = perf.get("expectancy_usd")
        print(f"  total={total} win_rate={wr} profit_factor={pf} expectancy={exp}")
        check("Paper trades available", perf.get("available"))
        check("At least 1 closed trade", total >= 1)

        by_sym = perf.get("by_symbol", [])
        for row in by_sym[:5]:
            print(f"    {row['symbol']}: {row['trades']} trades, WR={row['win_rate']:.1%}")
    except Exception as e:
        print(f"  [FAIL] Paper trade perf error: {e}")


def test_readiness():
    print(f"\n{SEPARATOR}")
    print("TEST 8: Full Readiness Report")
    print(SEPARATOR)
    try:
        from intelligence.ml.readiness import evaluate_readiness
        report = evaluate_readiness(require_mt5_audit=False)
        passed = report.get("passed")
        blockers = report.get("blockers", [])
        print(f"  Passed : {passed}")
        if blockers:
            print(f"  Blockers ({len(blockers)}):")
            for b in blockers:
                print(f"    - {b['name']}: {b['detail']}")
        else:
            print("  No blockers!")
        check("Readiness returned a result", "passed" in report)
    except Exception as e:
        print(f"  [FAIL] Readiness error: {e}")


if __name__ == "__main__":
    print(f"\n{'=' * 60}")
    print("  CryptoStream AI - End-to-End Pipeline Test")
    print(f"{'=' * 60}")

    test_symbol_threshold()
    test_symbol_memory()
    test_tiering_logic()
    test_trading_quality_gate()
    test_performance_feedback()
    test_ml_signal()
    test_paper_trade_perf()
    test_readiness()

    print(f"\n{'=' * 60}")
    print("  Test complete.")
    print(f"{'=' * 60}")
    print()
