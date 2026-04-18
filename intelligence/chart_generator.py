"""
CryptoStream AI — Chart Generator
Generates candlestick charts with support/resistance trendlines.
Output: base64-encoded PNG for use with Gemini Vision.
Port of QuantAgent's graph_util.py trendline math (no TA-Lib dependency).
"""

import io
import base64
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Trendline math (ported from QuantAgent graph_util.py)
# ──────────────────────────────────────────────────────────────────────────────

def _check_trend_line(support: bool, pivot: int, slope: float, y: pd.Series) -> float:
    intercept = -slope * pivot + y.iloc[pivot]
    line_vals = slope * np.arange(len(y)) + intercept
    diffs = line_vals - y.values
    if support and diffs.max() > 1e-5:
        return -1.0
    elif not support and diffs.min() < -1e-5:
        return -1.0
    return float((diffs ** 2.0).sum())


def _optimize_slope(support: bool, pivot: int, init_slope: float, y: pd.Series) -> tuple:
    slope_unit = (y.max() - y.min()) / len(y)
    opt_step = 1.0
    min_step = 0.0001
    curr_step = opt_step
    best_slope = init_slope
    best_err = _check_trend_line(support, pivot, init_slope, y)
    if best_err < 0:
        return (init_slope, -init_slope * pivot + y.iloc[pivot])

    get_derivative = True
    derivative = None
    iterations = 0

    while curr_step > min_step and iterations < 500:
        iterations += 1
        if get_derivative:
            sc = best_slope + slope_unit * min_step
            te = _check_trend_line(support, pivot, sc, y)
            derivative = te - best_err
            if te < 0.0:
                sc = best_slope - slope_unit * min_step
                te = _check_trend_line(support, pivot, sc, y)
                derivative = best_err - te
            if te < 0.0:
                break
            get_derivative = False

        test_slope = (
            best_slope - slope_unit * curr_step if derivative > 0.0
            else best_slope + slope_unit * curr_step
        )
        te = _check_trend_line(support, pivot, test_slope, y)
        if te < 0 or te >= best_err:
            curr_step *= 0.5
        else:
            best_err = te
            best_slope = test_slope
            get_derivative = True

    return (best_slope, -best_slope * pivot + y.iloc[pivot])


def _fit_trendlines_high_low(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple:
    """Fit support trendline on lows and resistance on highs."""
    x = np.arange(len(close))
    coefs = np.polyfit(x, close.values, 1)
    line_pts = coefs[0] * x + coefs[1]
    upper_pivot = int((high.values - line_pts).argmax())
    lower_pivot = int((low.values - line_pts).argmin())
    support_coefs = _optimize_slope(True, lower_pivot, coefs[0], low)
    resist_coefs = _optimize_slope(False, upper_pivot, coefs[0], high)
    return support_coefs, resist_coefs


# ──────────────────────────────────────────────────────────────────────────────
# Chart generators
# ──────────────────────────────────────────────────────────────────────────────

def _df_to_mpf(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare DataFrame for mplfinance (index = DatetimeIndex)."""
    mpf_df = df[["Datetime", "Open", "High", "Low", "Close", "Volume"]].copy()
    mpf_df = mpf_df.set_index("Datetime")
    mpf_df.index = pd.DatetimeIndex(mpf_df.index)
    return mpf_df


def _fig_to_base64(fig) -> str:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", pad_inches=0.1)
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return img_b64


def generate_kline_chart(df: pd.DataFrame, symbol: str = "") -> str:
    """
    Generate a basic candlestick chart.

    Args:
        df: OHLCV DataFrame (with Datetime index or column)
        symbol: label for chart title

    Returns:
        base64-encoded PNG string
    """
    try:
        import mplfinance as mpf
        import matplotlib.pyplot as plt
        matplotlib_use_agg()

        mpf_df = _df_to_mpf(df.tail(40))

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            gridstyle="--",
            gridcolor="#1e293b",
            facecolor="#0f172a",
            figcolor="#0f172a",
            edgecolor="#334155",
        )

        fig, axes = mpf.plot(
            mpf_df,
            type="candle",
            style=style,
            figsize=(12, 6),
            volume=True,
            title=f"\n{symbol} — Price Action",
            returnfig=True,
            block=False,
        )
        axes[0].set_ylabel("Price (USDT)", color="#94a3b8")
        return _fig_to_base64(fig)

    except Exception as e:
        logger.error(f"ChartGenerator: kline chart error: {e}")
        return ""


def generate_trend_chart(df: pd.DataFrame, symbol: str = "") -> str:
    """
    Generate a candlestick chart with support/resistance trendlines.

    Args:
        df: OHLCV DataFrame
        symbol: label for chart title

    Returns:
        base64-encoded PNG string
    """
    try:
        import mplfinance as mpf
        import matplotlib.pyplot as plt
        matplotlib_use_agg()

        candles = df.tail(50).copy().reset_index(drop=True)
        mpf_df = _df_to_mpf(candles)

        # Compute trendlines
        support_coefs, resist_coefs = _fit_trendlines_high_low(
            candles["High"], candles["Low"], candles["Close"]
        )
        n = len(candles)
        xs = np.arange(n)
        support_line = support_coefs[0] * xs + support_coefs[1]
        resist_line  = resist_coefs[0]  * xs + resist_coefs[1]

        apds = [
            mpf.make_addplot(support_line, color="#22c55e", width=1.5, label="Support"),
            mpf.make_addplot(resist_line,  color="#ef4444", width=1.5, label="Resistance"),
        ]

        # Optional: EMA overlays if available
        if "ema_20" in candles.columns and candles["ema_20"].notna().sum() > 5:
            apds.append(mpf.make_addplot(
                candles["ema_20"].values, color="#f59e0b", width=1, label="EMA20"
            ))
        if "ema_50" in candles.columns and candles["ema_50"].notna().sum() > 5:
            apds.append(mpf.make_addplot(
                candles["ema_50"].values, color="#818cf8", width=1, label="EMA50"
            ))

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            gridstyle="--",
            gridcolor="#1e293b",
            facecolor="#0f172a",
            figcolor="#0f172a",
            edgecolor="#334155",
        )

        fig, axes = mpf.plot(
            mpf_df,
            type="candle",
            style=style,
            figsize=(12, 6),
            volume=False,
            addplot=apds,
            title=f"\n{symbol} — Trend Channel",
            returnfig=True,
            block=False,
        )
        axes[0].set_ylabel("Price (USDT)", color="#94a3b8")
        axes[0].legend(
            ["Support", "Resistance", "EMA20", "EMA50"],
            loc="upper left",
            facecolor="#1e293b",
            edgecolor="#475569",
            labelcolor="#e2e8f0",
            fontsize=8,
        )

        return _fig_to_base64(fig)

    except Exception as e:
        logger.error(f"ChartGenerator: trend chart error: {e}")
        return ""


def generate_indicator_chart(df: pd.DataFrame, symbol: str = "") -> str:
    """
    Generate a multi-panel chart: Candlestick + RSI + MACD.

    Returns:
        base64-encoded PNG string
    """
    try:
        import mplfinance as mpf
        import matplotlib.pyplot as plt
        matplotlib_use_agg()

        candles = df.tail(40).copy().reset_index(drop=True)
        mpf_df = _df_to_mpf(candles)

        apds = []
        if "rsi_14" in candles.columns:
            apds.append(mpf.make_addplot(
                candles["rsi_14"].values, panel=1, color="#f59e0b",
                ylabel="RSI", ylim=(0, 100)
            ))
            # Overbought/oversold lines
            apds.append(mpf.make_addplot(
                [70] * len(candles), panel=1, color="#ef4444",
                linestyle="--", width=0.5
            ))
            apds.append(mpf.make_addplot(
                [30] * len(candles), panel=1, color="#22c55e",
                linestyle="--", width=0.5
            ))

        if "macd_hist" in candles.columns:
            hist = candles["macd_hist"].values
            colors = ["#22c55e" if v >= 0 else "#ef4444" for v in hist]
            apds.append(mpf.make_addplot(
                hist, panel=2, type="bar", color=colors, ylabel="MACD Hist"
            ))

        style = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            gridstyle="--",
            gridcolor="#1e293b",
            facecolor="#0f172a",
            figcolor="#0f172a",
        )

        fig, _ = mpf.plot(
            mpf_df,
            type="candle",
            style=style,
            figsize=(12, 9),
            volume=False,
            addplot=apds if apds else [],
            panel_ratios=(3, 1, 1) if apds else (1,),
            title=f"\n{symbol} — Technical Indicators",
            returnfig=True,
            block=False,
        )
        return _fig_to_base64(fig)

    except Exception as e:
        logger.error(f"ChartGenerator: indicator chart error: {e}")
        return ""


def matplotlib_use_agg():
    """Ensure matplotlib uses Agg backend (no display required)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
    except Exception:
        pass
