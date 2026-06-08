from __future__ import annotations

from typing import Any, Iterable


def _normalize_index_requests(
    requested: Iterable[str] | None,
    *,
    alias_map: dict[str, str],
    ticker_map: dict[str, str],
    fallback: list[str],
) -> list[str]:
    normalized: list[str] = []
    for item in (requested or fallback):
        canonical = alias_map.get(str(item).upper().strip(), str(item).upper().strip())
        if canonical in ticker_map and canonical not in normalized:
            normalized.append(canonical)
    return normalized or list(fallback)


def _summarize_index_close_series(close, *, label: str, ticker: str) -> dict[str, Any] | None:
    if close is None or getattr(close, "empty", True) or len(close) < 30:
        return None

    start_price = float(close.iloc[0])
    end_price = float(close.iloc[-1])
    total_return = (end_price / start_price) - 1.0 if start_price > 0 else 0.0
    observed_years = max((close.index[-1] - close.index[0]).days / 365.25, 0.25)
    cagr = (end_price / start_price) ** (1.0 / observed_years) - 1.0 if start_price > 0 else 0.0

    running_max = close.cummax()
    drawdown = (close / running_max) - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0

    ma50 = float(close.tail(50).mean()) if len(close) >= 50 else end_price
    ma200 = float(close.tail(200).mean()) if len(close) >= 200 else float(close.mean())
    trend = "bullish" if end_price >= ma50 >= ma200 else "mixed" if end_price >= ma200 else "bearish"

    one_year_return = None
    if len(close) >= 252:
        one_year_return = (end_price / float(close.iloc[-252])) - 1.0

    return {
        "label": label,
        "ticker": ticker,
        "start_date": close.index[0].strftime("%Y-%m-%d"),
        "end_date": close.index[-1].strftime("%Y-%m-%d"),
        "start_price": round(start_price, 2),
        "end_price": round(end_price, 2),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "one_year_return_pct": round(one_year_return * 100, 2) if one_year_return is not None else None,
        "current_vs_ma50_pct": round(((end_price / ma50) - 1.0) * 100, 2) if ma50 else None,
        "current_vs_ma200_pct": round(((end_price / ma200) - 1.0) * 100, 2) if ma200 else None,
        "trend": trend,
    }


def _build_index_summary_response(
    *,
    years: int,
    summaries: dict[str, dict[str, Any]],
    ranking: list[tuple[str, float]],
) -> dict[str, Any]:
    ordered = sorted(ranking, key=lambda item: item[1], reverse=True)
    return {
        "status": "SUCCESS",
        "years": years,
        "indices": summaries,
        "best_index": ordered[0][0],
        "worst_index": ordered[-1][0],
        "ranking": [
            {
                "index": key,
                "label": summaries[key]["label"],
                "total_return_pct": round(score * 100, 2),
                "trend": summaries[key]["trend"],
            }
            for key, score in ordered
        ],
        "source": "yfinance",
    }
