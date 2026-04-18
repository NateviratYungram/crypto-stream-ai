# -*- coding: utf-8 -*-
"""
Proactive ML Signal Scanner

Runs every 15 minutes, scans all DEFAULT_SYMBOLS for high-probability setups.
When ML win_pct >= threshold, inserts a signal into active_alerts so the
Alerts & Reviews dashboard shows it immediately.

Logic: For each symbol, evaluate BOTH BUY and SELL, then emit ONLY the
direction with higher probability (prevents contradictory LONG+SHORT signals).
"""
import os
import sqlite3
import psycopg2
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta

from intelligence.ml.signal_model import DEFAULT_SYMBOLS, predict_win_probability
from intelligence.ml.feature_extractor import extract_features

load_dotenv()
from intelligence.technical_engine import get_kline_data, compute_indicators

logger = logging.getLogger(__name__)

PERSISTENCE_DB  = "persistence.db"
SCAN_THRESHOLD  = 70   # minimum win_pct % to generate an alert
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
    from datetime import timezone
    import zoneinfo
    try:
        et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        # fallback: UTC-4 (EDT approximation)
        et = datetime.utcnow().replace(tzinfo=timezone.utc).astimezone(
            type('tz', (), {'utcoffset': lambda s, dt: __import__('datetime').timedelta(hours=-4),
                            'tzname': lambda s, dt: 'EDT', 'dst': lambda s, dt: None})()
        )
    if et.weekday() >= 5:   # Saturday=5, Sunday=6
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
    us_open = _us_market_open()

    for (sym, asset_class, tf) in DEFAULT_SYMBOLS:
        if tf != "1h":
            continue
        if sym in scanned_syms:
            continue
        # Skip US stocks when market is closed — no live data available
        if asset_class == "STOCK" and not us_open:
            logger.debug(f"[ML-Scanner] Skipping {sym} (STOCK, US market closed)")
            continue
        scanned_syms.add(sym)

        try:
            df = get_kline_data(sym, timeframe="1h", limit=300, asset_class=asset_class)
            if df is None or len(df) < 50:
                continue

            df = compute_indicators(df)
            sent_v = _get_sentiment(sym)

            # Evaluate both directions
            best_side    = None
            best_win_pct = 0.0
            best_result  = None

            for side in ("BUY", "SELL"):
                try:
                    feats  = extract_features(df, len(df) - 1, side=side, asset_class=asset_class, sentiment_score=sent_v)
                    result = predict_win_probability(feats)
                    if not result.get("available"):
                        continue
                    win_pct = result["win_pct"]
                    if win_pct > best_win_pct:
                        best_win_pct = win_pct
                        best_side    = side
                        best_result  = result
                except Exception as se:
                    logger.debug(f"[ML-Scanner] {sym}/{side} predict error: {se}")

            # Only emit if best direction is above threshold
            if best_side is None or best_win_pct < threshold:
                continue

            # Deduplicate: skip if active ML alert already exists for this symbol (any direction)
            cursor.execute("""
                SELECT id FROM active_alerts
                WHERE symbol = ? AND user_id = 'ml_scanner'
                      AND status = 'ACTIVE' AND created_at > ?
            """, (sym, cutoff))

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
            tg_msg = (
                f"{emoji} *ML Signal — {sym}*\n"
                f"Direction: *{direction}*\n"
                f"Win Probability: *{best_win_pct:.0f}%*\n"
                f"Model AUC: {auc:.3f}\n"
                f"Scanned: {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
                f"⚠️ _ไม่ใช่คำแนะนำการซื้อขาย_"
            )
            _send_telegram(tg_msg)

        except Exception as exc:
            errors += 1
            logger.debug(f"[MLScanner] {sym} error: {exc}")

    conn.commit()
    conn.close()

    return {"scanned": len(scanned_syms), "found": found, "skipped_duplicates": skipped_dup, "errors": errors}
