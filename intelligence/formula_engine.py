import logging
from typing import Any, Union

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)

def SMA(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()

def EMA(series: pd.Series, window: int) -> pd.Series:
    return ta.trend.EMAIndicator(close=series, window=window).ema_indicator()

def RSI(series: pd.Series, window: int) -> pd.Series:
    return ta.momentum.RSIIndicator(close=series, window=window).rsi()

def ATR(df: pd.DataFrame, window: int) -> pd.Series:
    return ta.volatility.AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=window).average_true_range()

def evaluate_formula(df: pd.DataFrame, formula: str) -> Union[float, pd.Series]:
    """
    Evaluates a technical analysis formula against a OHLCV DataFrame.
    Example: "SMA(Close, 20) / Close * 100"
    """
    # Clean formula
    formula = formula.strip()

    # Prepare namespace
    # We map common terms to the DataFrame columns
    namespace = {
        'CLOSE': df['Close'],
        'OPEN': df['Open'],
        'HIGH': df['High'],
        'LOW': df['Low'],
        'VOLUME': df['Volume'],
        'SMA': SMA,
        'EMA': EMA,
        'RSI': RSI,
        'ATR': lambda w: ATR(df, w),
        'ABS': abs,
        'MIN': min,
        'MAX': max,
        'NP': np,
    }

    # Add lowercase versions for convenience
    namespace.update({k.lower(): v for k, v in namespace.items()})

    try:
        # Use a restricted eval. In production, a more robust DSL parser is recommended.
        # But for this internal tool, a restricted eval is a good balance between speed and flexibility.
        result = eval(formula, {"__builtins__": {}}, namespace)

        # If the result is a Series, take the last non-NaN value or return the series
        if isinstance(result, pd.Series):
            return result
        return result
    except Exception as e:
        logger.error(f"Formula evaluation error for '{formula}': {e}")
        raise ValueError(f"Invalid formula: {e}")

def get_latest_value(result: Any) -> float:
    """Helper to extract the latest float value from an evaluation result."""
    if isinstance(result, pd.Series):
        # Find the last non-NaN value
        valid_vals = result.dropna()
        if not valid_vals.empty:
            return float(valid_vals.iloc[-1])
        return 0.0
    try:
        return float(result)
    except (TypeError, ValueError):
        return 0.0
