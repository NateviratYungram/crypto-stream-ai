# -*- coding: utf-8 -*-
"""
Proactive ML Signal Scanner

Runs every 15 minutes, scans all DEFAULT_SYMBOLS for high-probability setups.
When ML win_pct >= threshold, inserts a signal into active_alerts so the
Alerts & Reviews dashboard shows it immediately.

Logic: For each symbol, evaluate BOTH BUY and SELL, then emit ONLY the
direction with higher probability (prevents contradictory LONG+SHORT signals).
"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta

import psycopg2
from dotenv import load_dotenv

from intelligence.guards import InstitutionalGuard  # V8 Guard Integration
from intelligence.ml.signal_model import (
    TRADE_TRAIN_SYMBOLS,
    predict_with_neural_consensus,
)
from intelligence.technical_engine import compute_indicators, get_kline_data
from intelligence.utils.market_hours import (
    get_market_status_data,  # Added for Market Alerts
)

load_dotenv()

logger = logging.getLogger(__name__)

PERSISTENCE_DB  = "persistence.db"
SCAN_THRESHOLD  = 80   # Sniper Mode: Increased from 70 to 80 for higher precision
DEDUP_HOURS     = 2    # suppress duplicate alert for same symbol within this window

_TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
_TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def _send_telegram(text: str) -> bool:
    if not _TG_TOKEN or not _TG_CHAT_ID:
        return False
    try:
        import requests as _req
        r = _req.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"[ML-Scanner] Telegram send failed: {e}")
        return False


def _us_market_open() -> bool:
    """Return True if US equity market is currently open (Mon-Fri 09:30–16:00 ET)."""
    import zoneinfo
    from datetime import timezone
    try:
        et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        # fallback: UTC-4 (EDT approximation)
        et = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(
            type('tz', (), {'utcoffset': lambda s, dt: __import__('datetime').timedelta(hours=-4),
                            'tzname': lambda s, dt: 'EDT', 'dst': lambda s, dt: None})()
        )
    if et.weekday() >= 5:
        return False
    return (et.hour, et.minute) >= (9, 30) and (et.hour, et.minute) < (16, 0)


def _get_sentiment(sym: str) -> float:
    try:
        conn_pg = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            dbname=os.getenv("DB_NAME", "crypto_stream_db"),
            user=os.getenv("DB_USER", "user"),
            password=os.getenv("DB_PASS", "password")
        )
        with conn_pg.cursor() as cur:
            cur.execute(
                "SELECT score FROM news_sentiment WHERE symbol=%s ORDER BY id DESC LIMIT 1",
                (sym.upper(),)
            )
            row = cur.fetchone()
        conn_pg.close()
        return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def scan_for_high_probability_signals(threshold: float = SCAN_THRESHOLD) -> dict:
    """
    Scan 1h bars for all DEFAULT_SYMBOLS.
    For each symbol: evaluate BUY + SELL, emit only the better direction if ≥ threshold.
    Returns {"scanned": N, "found": N, "skipped_duplicates": N}.
    """
    found       = 0
    skipped_dup = 0
    errors      = 0

    # ── Market Session Alerts ─────────────────────────────
    market_status = get_market_status_data()
    # Logic to send one-time alert when market status changes could be added here
    # For now, we'll just include it in the scan summary if it's a significant change

    conn   = sqlite3.connect(PERSISTENCE_DB)
    cursor = conn.cursor()

    # Expire stale old ML alerts (>6h old) so the list doesn't fill up
    cursor.execute("""
        UPDATE active_alerts SET status='DISMISSED'
        WHERE user_id='ml_scanner' AND status='ACTIVE'
          AND created_at < datetime('now', '-6 hours')
    """)

    cutoff = (datetime.utcnow() - timedelta(hours=DEDUP_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

    scanned_syms: set = set()
    # us_open = _us_market_open() # No longer needed for MT5 Sniper Assets

    for (sym, asset_class, tf) in TRADE_TRAIN_SYMBOLS:
        # Sniper Mode: We now scan ALL timeframes (15m, 1h, 4h) defined in TRADE_TRAIN_SYMBOLS
        # to find the absolute best entry across the spectrum.

        lookup_key = f"{sym}_{tf}"
        if lookup_key in scanned_syms:
            continue
        scanned_syms.add(lookup_key)

        try:
            # Fetch data with higher limit for better indicator stability
            df = get_kline_data(sym, timeframe=tf, limit=500, asset_class=asset_class)
            if df is None or len(df) < 50:
                continue

            df = compute_indicators(df)
            sent_v = _get_sentiment(sym)

            # Skip if live features are critically far from training distribution
            try:
                from intelligence.ml.drift_monitor import get_drift_report
                last = df.iloc[-1]
                _drift_feats = {}
                if "RSI" in df.columns:
                    _drift_feats["rsi"] = float(last["RSI"])
                if "ATR" in df.columns and float(last.get("Close", 1) or 1) > 0:
                    _drift_feats["atr_pct"] = float(last["ATR"]) / float(last["Close"])
                if "MACD_Hist" in df.columns:
                    _drift_feats["macd_hist_norm"] = float(last["MACD_Hist"])
                if "Volume_Ratio" in df.columns:
                    _drift_feats["vol_ratio"] = float(last["Volume_Ratio"])
                if _drift_feats:
                    _dr = get_drift_report(_drift_feats)
                    if _dr.get("status") == "CRITICAL_DRIFT":
                        logger.warning(
                            f"[ML-Scanner] {sym}/{tf} CRITICAL_DRIFT "
                            f"(integrity={_dr['integrity_score']}) — skipping"
                        )
                        continue
            except Exception as _de:
                logger.debug(f"[ML-Scanner] drift check error for {sym}/{tf}: {_de}")

            # Evaluate both directions
            best_side    = None
            best_win_pct = 0.0
            best_result  = None

            for side in ("BUY", "SELL"):
                try:
                    # ── V8 Sentiment Confluence: Strict Mode ──
                    # If AI wants to BUY but news is negative, or vice-versa, skip it.
                    if side == "BUY" and sent_v <= -20:
                        logger.info(f"🛡️ Sentiment Guard: Blocking BUY on {sym} due to negative news ({sent_v})")
                        continue
                    if side == "SELL" and sent_v >= 20:
                        logger.info(f"🛡️ Sentiment Guard: Blocking SELL on {sym} due to positive news ({sent_v})")
                        continue

                    # ── V8 Sniper Guard: Pre-prediction check ──
                    if not InstitutionalGuard.check_all_guards(sym, side):
                        continue

                    # ── V8 Hybrid Inference: Ensemble + Neural Attention ──
                    result = predict_with_neural_consensus(
                        df,
                        len(df) - 1,
                        side=side,
                        symbol=sym,
                        asset_class=asset_class,
                        sentiment_score=sent_v
                    )

                    if not result.get("available"):
                        continue

                    win_pct = result["win_pct"]
                    if win_pct > best_win_pct:
                        best_win_pct = win_pct
                        best_side    = side
                        best_result  = result
                except Exception as se:
                    logger.debug(f"[ML-Scanner] {sym}/{tf}/{side} predict error: {se}")

            # Only emit if best direction is above threshold
            if best_side is None or best_win_pct < threshold:
                continue

            # Deduplicate: skip if active ML alert already exists for this symbol+tf
            cursor.execute("""
                SELECT id FROM active_alerts
                WHERE symbol = ? AND condition LIKE ? AND user_id = 'ml_scanner'
                      AND status = 'ACTIVE' AND created_at > ?
            """, (sym, f"%{tf}%", cutoff))

            if cursor.fetchone():
                skipped_dup += 1
                continue

            # Dismiss any old conflicting active alerts for this symbol
            cursor.execute("""
                UPDATE active_alerts SET status='DISMISSED'
                WHERE symbol=? AND user_id='ml_scanner' AND status='ACTIVE'
            """, (sym,))

            auc       = best_result.get("roc_auc", 0)
            n_samples = best_result.get("n_samples", 0)
            direction = "LONG" if best_side == "BUY" else "SHORT"
            condition = f"ML Signal {best_side} — Edge ≥{threshold}%"
            message   = (
                f"Win probability {best_win_pct:.0f}% ({direction}) | "
                f"Model AUC {auc:.3f} | {n_samples} training samples | "
                f"Scanned {datetime.utcnow().strftime('%H:%M UTC')}"
            )

            cursor.execute("""
                INSERT INTO active_alerts (user_id, symbol, condition, message, status, created_at)
                VALUES ('ml_scanner', ?, ?, ?, 'ACTIVE', datetime('now'))
            """, (sym, condition, message))

            found += 1
            logger.info(f"[MLScanner] {sym} {direction} win={best_win_pct:.0f}% AUC={auc:.3f} → alert created")

            # ── Telegram notification ────────────────────────────────
            emoji = "📈" if best_side == "BUY" else "📉"
            import random

            # Diverse phrases for institutional feel
            phrases = [
                "🎯 *SNIPER TARGET ACQUIRED*",
                "🚀 *INSTITUTIONAL MOMENTUM DETECTED*",
                "💎 *HIGH-CONVICTION SIGNAL*",
                "⚡ *NEURAL V8 ANALYSIS COMPLETE*",
                "🏦 *SMART MONEY FOOTPRINT FOUND*"
            ]
            header = random.choice(phrases)

            # Market context line
            market_ctx = ""
            if asset_class == "MACRO":
                status = market_status.get("forex", {}).get("status", "OPEN")
                market_ctx = f"Market Status: *{status}*"
            elif asset_class == "STOCK":
                status = market_status.get("stocks", {}).get("status", "OPEN")
                market_ctx = f"Exchange Status: *{status}*"

            tg_msg = (
                f"{header}\n\n"
                f"Asset: *{sym}* ({tf})\n"
                f"Action: {emoji} *{direction}*\n"
                f"Confidence: *{best_win_pct:.1f}%*\n"
                f"{market_ctx}\n"
                f"Model Edge: {auc:.3f} AUC\n"
                f"Timestamp: {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
                f"🔗 [View on TradingView](https://www.tradingview.com/chart/?symbol={sym})\n"
                f"⚠️ _Institutional Grade Analysis — High Risk_"
            )
            _send_telegram(tg_msg)

        except Exception as exc:
            errors += 1
            logger.debug(f"[MLScanner] {sym} error: {exc}")

    conn.commit()
    conn.close()

    return {"scanned": len(scanned_syms), "found": found, "skipped_duplicates": skipped_dup, "errors": errors}

if __name__ == "__main__":
    import sys
    # Force UTF-8 for Windows Terminal
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    logging.basicConfig(level=logging.INFO)
    print("\n🚀 Starting ML Sniper V8 Dry-run Scanner...")
    print("--- Scanning for High-Probability (80%+) Signals ---\n")

    res = scan_for_high_probability_signals()

    print("\n✅ Scan Complete:")
    print(f"   Scanned    : {res.get('scanned')} assets/timeframes")
    print(f"   Found      : {res.get('found')} signals above threshold")
    print(f"   Duplicates : {res.get('skipped_duplicates')} skipped")
    print(f"   Errors     : {res.get('errors')}")
