import chat_server
from intelligence import mt5_connector


def test_telegram_paper_entry_price_prefers_existing_price(monkeypatch):
    monkeypatch.setattr(
        chat_server,
        "_get_live_price",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("should not be called")),
    )

    price = chat_server._telegram_resolve_paper_entry_price("GOLD", "BUY", 4661.25)

    assert price == 4661.25


def test_telegram_paper_entry_price_uses_mt5_ask_for_buy(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "resolve_broker_symbol",
        lambda symbol: {
            "status": "SUCCESS",
            "symbol": "XAUUSD",
            "quote": {"bid": 4660.10, "ask": 4660.32, "last": 4660.21},
        },
    )
    monkeypatch.setattr(
        chat_server,
        "_get_live_price",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("market fallback failed")),
    )

    price = chat_server._telegram_resolve_paper_entry_price("GOLD", "BUY")

    assert price == 4660.32


def test_telegram_paper_entry_price_uses_mt5_bid_for_sell(monkeypatch):
    monkeypatch.setattr(
        mt5_connector,
        "resolve_broker_symbol",
        lambda symbol: {
            "status": "SUCCESS",
            "symbol": "XAUUSD",
            "quote": {"bid": 4660.10, "ask": 4660.32, "last": 4660.21},
        },
    )
    monkeypatch.setattr(
        chat_server,
        "_get_live_price",
        lambda symbol: (_ for _ in ()).throw(RuntimeError("market fallback failed")),
    )

    price = chat_server._telegram_resolve_paper_entry_price("GOLD", "SELL")

    assert price == 4660.10

