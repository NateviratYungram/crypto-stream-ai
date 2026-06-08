from chat_server_symbol_helpers import (
    TRADE_SYMBOL_ALIASES,
    _canonical_trade_symbol,
    _telegram_extract_symbol,
    _telegram_symbols_from_text,
    _trade_symbol_aliases,
    resolve_trade_symbol,
)


def test_telegram_extract_symbol_handles_aliases_and_regex():
    assert _telegram_extract_symbol("watch gold now") == "GOLD"
    assert _telegram_extract_symbol("trade nas100 breakout") == "NASDAQ"
    assert _telegram_extract_symbol("look at eur/usd") == "EURUSD"
    assert _telegram_extract_symbol("nothing here", default="BTC") == "BTC"


def test_trade_symbol_aliases_deduplicates_and_normalizes():
    aliases = _trade_symbol_aliases("xau/usd")

    assert aliases[0] == "XAUUSD"
    assert "GOLD" in aliases
    assert _trade_symbol_aliases("") == []


def test_canonical_trade_symbol_prefers_expected_core_symbol():
    assert _canonical_trade_symbol("xauusd") == "GOLD"
    assert _canonical_trade_symbol("btc") == "BTCUSD"
    assert _canonical_trade_symbol("eth") == "ETHUSD"
    assert _canonical_trade_symbol(None) == ""


def test_resolve_trade_symbol_builds_cross_layer_variants():
    btc = resolve_trade_symbol("btc")
    gold = resolve_trade_symbol("xauusd")
    sol = resolve_trade_symbol("sol")

    assert btc["canonical"] == "BTCUSD"
    assert btc["tactics_symbol"] == "BTC"
    assert btc["paper_symbol"] == "BTCUSD"
    assert gold["canonical"] == "GOLD"
    assert gold["tactics_symbol"] == "GOLD"
    assert sol["paper_symbol"] == "SOLUSDT"


def test_telegram_symbols_from_text_extracts_multiple_symbols():
    result = _telegram_symbols_from_text("watch btc gold nas100 and eurusd with 0.01 lot")

    assert result == ["BTC", "EURUSD", "GOLD", "NASDAQ"]


def test_trade_symbol_alias_map_contains_expected_keys():
    assert "BTCUSD" in TRADE_SYMBOL_ALIASES
    assert "GOLD" in TRADE_SYMBOL_ALIASES
