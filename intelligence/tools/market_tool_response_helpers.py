from __future__ import annotations

from typing import Any


def _select_market_opportunity_heroes(
    groups: dict[str, dict[str, Any]],
    hero_priority: list[str] | None = None,
) -> dict[str, Any]:
    priority = hero_priority or ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE", "CRYPTO"]
    hero_symbol = None
    hero_exchange = None
    hero_loser = None
    hero_loser_exchange = None

    for key in priority:
        if key not in groups:
            continue
        group = groups[key]
        if not hero_symbol and group.get("top_gainer"):
            hero_symbol = group["top_gainer"]["symbol"]
            hero_exchange = group["top_gainer"].get("exchange")
        if not hero_loser and group.get("top_loser"):
            hero_loser = group["top_loser"]["symbol"]
            hero_loser_exchange = group["top_loser"].get("exchange")
        if hero_symbol and hero_loser:
            break

    return {
        "hero_symbol": hero_symbol,
        "hero_exchange": hero_exchange,
        "hero_loser": hero_loser,
        "hero_loser_exchange": hero_loser_exchange,
    }


def _build_market_opportunities_response(
    *,
    fetched_at: str,
    groups: dict[str, dict[str, Any]],
    data_source: str = "Yahoo Finance Screener (realtime)",
    confidence: str = "HIGH — live data, volume-filtered (>500K shares), index membership verified",
) -> dict[str, Any]:
    heroes = _select_market_opportunity_heroes(groups)
    return {
        "data_source": data_source,
        "fetched_at": fetched_at,
        "confidence": confidence,
        "groups": groups,
        **heroes,
        "instruction": (
            "CRITICAL PRESENTATION RULES:\n"
            "1. Each group in 'groups' is INDEPENDENT — present them in SEPARATE sections.\n"
            "   Do NOT mix stocks from different groups.\n"
            "2. Group keys: NASDAQ_100, SP500, NASDAQ_COMPOSITE, CRYPTO\n"
            "   • NASDAQ_100: top 100 large-cap non-financial NASDAQ stocks\n"
            "   • SP500: 500 largest US companies across all exchanges\n"
            "   • NASDAQ_COMPOSITE: all other NASDAQ-listed stocks (smaller, higher risk)\n"
            "   • CRYPTO: top cryptocurrencies by market cap\n"
            "3. For each group show: top_gainer and top_loser with symbol, name, change_percent,\n"
            "   current_price, volume, market_state, and news_headlines.\n"
            "4. market_state: REGULAR = market hours | PRE = pre-market | POST = after-hours\n"
            "5. Always show fetched_at timestamp and data_source for transparency.\n"
            "6. Volume confirms liquidity — always mention it. Format: 14.3M, 850K, etc."
        ),
    }


def _interpret_market_features(row: dict[str, Any], symbol: str) -> str:
    parts: list[str] = []
    r30 = row.get("return_30d")
    if r30 is not None:
        parts.append(f"{symbol} returned {float(r30) * 100:+.1f}% over the past 30 days")
    vol30 = row.get("volatility_30d")
    if vol30 is not None:
        level = (
            "highly volatile"
            if float(vol30) > 0.5
            else "moderately volatile"
            if float(vol30) > 0.2
            else "relatively stable"
        )
        parts.append(f"is {level} ({float(vol30) * 100:.0f}% annualized vol)")
    corr_sp500 = row.get("corr_vs_sp500_30d")
    if corr_sp500 is not None:
        correlation = float(corr_sp500)
        coupling = (
            "strongly correlated"
            if correlation > 0.7
            else "moderately correlated"
            if correlation > 0.4
            else "weakly correlated"
            if correlation > 0.1
            else "decoupled"
        )
        parts.append(f"{coupling} with SP500 (r={correlation:.2f} over 30d)")
    beta = row.get("beta_vs_sp500")
    if beta is not None:
        beta_value = float(beta)
        parts.append(f"beta vs SP500 = {beta_value:.2f} ({'more' if beta_value > 1 else 'less'} risky than market)")
    rel = row.get("rel_strength_30d")
    if rel is not None:
        relative_strength = float(rel) * 100
        parts.append(
            f"{'outperformed' if relative_strength > 0 else 'underperformed'} SP500 by {abs(relative_strength):.1f}pp over 30d"
        )
    return ". ".join(parts) + "." if parts else "Insufficient data for interpretation."


def _build_market_features_response(
    *,
    symbol: str,
    row: dict[str, Any],
    computed_date: str | None,
    interpret_features_fn=None,
) -> dict[str, Any]:
    def fmt_pct(value: Any) -> str:
        return f"{float(value) * 100:+.2f}%" if value is not None else "N/A"

    def fmt_corr(value: Any) -> str:
        return f"{float(value):.2f}" if value is not None else "N/A"

    interpreter = interpret_features_fn or _interpret_market_features
    return {
        "symbol": symbol.upper(),
        "as_of": computed_date,
        "returns": {
            "1d": fmt_pct(row.get("return_1d")),
            "7d": fmt_pct(row.get("return_7d")),
            "30d": fmt_pct(row.get("return_30d")),
            "90d": fmt_pct(row.get("return_90d")),
            "1y": fmt_pct(row.get("return_365d")),
        },
        "volatility_annualized": {
            "7d": fmt_pct(row.get("volatility_7d")),
            "30d": fmt_pct(row.get("volatility_30d")),
            "90d": fmt_pct(row.get("volatility_90d")),
        },
        "correlation": {
            "vs_sp500_30d": fmt_corr(row.get("corr_vs_sp500_30d")),
            "vs_sp500_90d": fmt_corr(row.get("corr_vs_sp500_90d")),
            "vs_btc_30d": fmt_corr(row.get("corr_vs_btc_30d")),
            "vs_btc_90d": fmt_corr(row.get("corr_vs_btc_90d")),
            "vs_gold_30d": fmt_corr(row.get("corr_vs_gold_30d")),
        },
        "beta_vs_sp500": fmt_corr(row.get("beta_vs_sp500")),
        "price_position": {
            "pct_from_52w_high": f"{float(row['pct_from_52w_high']):+.1f}%" if row.get("pct_from_52w_high") is not None else "N/A",
            "pct_from_52w_low": f"{float(row['pct_from_52w_low']):+.1f}%" if row.get("pct_from_52w_low") is not None else "N/A",
        },
        "relative_strength_vs_sp500_30d": fmt_pct(row.get("rel_strength_30d")),
        "interpretation": interpreter(row, symbol),
    }
