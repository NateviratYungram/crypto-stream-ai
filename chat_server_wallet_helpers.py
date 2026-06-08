from __future__ import annotations

import re
from typing import Any


def _is_eth_address(address: str) -> bool:
    return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", address or ""))


def _build_eth_assets(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    eth_section = payload.get("ETH") or {}
    assets: list[dict[str, Any]] = []
    total_usd = 0.0

    eth_balance = float(eth_section.get("balance") or 0.0)
    eth_price = float(((eth_section.get("price") or {}).get("rate")) or 0.0)
    eth_change = float(((eth_section.get("price") or {}).get("diff")) or 0.0)
    eth_usd = eth_balance * eth_price if eth_price > 0 else 0.0
    if eth_balance > 0 or eth_usd > 0:
        assets.append({
            "symbol": "ETH",
            "name": "Ethereum",
            "balance": round(eth_balance, 8),
            "price": round(eth_price, 8),
            "usd_value": round(eth_usd, 2),
            "change_24h": round(eth_change, 4),
            "allocation": 0.0,
            "kind": "native",
            "token_address": None,
            "logo": "",
            "priced": eth_price > 0,
        })
        total_usd += eth_usd

    for token_entry in payload.get("tokens") or []:
        token_info = token_entry.get("tokenInfo") or {}
        symbol = (token_info.get("symbol") or "").strip() or "TOKEN"
        decimals_raw = token_info.get("decimals")
        try:
            decimals = int(decimals_raw) if decimals_raw is not None and str(decimals_raw).strip() != "" else 0
        except Exception:
            decimals = 0
        raw_balance = token_entry.get("balance") or 0
        try:
            balance = float(raw_balance) / (10 ** decimals if decimals >= 0 else 1)
        except Exception:
            balance = 0.0

        price_info = token_info.get("price") or {}
        price = float(price_info.get("rate") or 0.0)
        change_24h = float(price_info.get("diff") or 0.0)
        usd_value = balance * price if price > 0 else 0.0
        if balance <= 0:
            continue
        if price <= 0 and balance < 1:
            continue
        if usd_value < 1 and price > 0:
            continue
        total_usd += usd_value
        assets.append({
            "symbol": symbol.upper(),
            "name": token_info.get("name") or symbol.upper(),
            "balance": round(balance, 8),
            "price": round(price, 8),
            "usd_value": round(usd_value, 2),
            "change_24h": round(change_24h, 4),
            "allocation": 0.0,
            "kind": "token",
            "token_address": token_info.get("address"),
            "logo": token_info.get("image") or "",
            "priced": price > 0,
        })

    total_usd = round(total_usd, 2)
    for asset in assets:
        asset["allocation"] = round((float(asset["usd_value"]) / total_usd) * 100, 2) if total_usd > 0 and float(asset["usd_value"]) > 0 else 0.0

    assets.sort(key=lambda item: (float(item["usd_value"]), float(item["balance"])), reverse=True)
    return assets, total_usd


def _build_eth_identity(identity: dict[str, Any] | None, explorer_url: str) -> dict[str, Any] | None:
    if not identity:
        return None
    return {
        "display_name": identity.get("display_name", ""),
        "resolved_name": identity.get("resolved_name", ""),
        "avatar": identity.get("avatar", ""),
        "description": identity.get("description", ""),
        "twitter": identity.get("twitter", ""),
        "website": identity.get("website", ""),
        "explorer_url": explorer_url,
    }


def _build_eth_portfolio_result(
    *,
    address: str,
    explorer_url: str,
    assets: list[dict[str, Any]],
    total_usd: float,
    identity: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "address": address,
        "chain": "ETH",
        "total_usd": total_usd,
        "assets": assets,
        "source": "Ethplorer public API (filtered positions)",
        "identity": _build_eth_identity(identity, explorer_url),
        "explorer_url": explorer_url,
    }
