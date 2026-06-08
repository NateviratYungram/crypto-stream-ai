from chat_server_query_helpers import (
    _extract_historical_years,
    _extract_index_history_targets,
    _extract_stock_history_direction,
    _extract_stock_history_universe,
    _is_broad_stock_history_query,
    _is_capability_question,
    _is_explicit_stock_ranking_request,
    _is_ranked_stock_history_query,
    _is_stock_top_performer_history_question,
    _normalize_query_text,
)


def test_normalize_query_text_cleans_case_and_zero_width():
    text = "NASDAq\u200b 100"
    assert _normalize_query_text(text) == "nasdaq 100"


def test_extract_historical_years_handles_decade_and_bounds():
    assert _extract_historical_years("show decade performance") == 10
    assert _extract_historical_years("top stocks 20 years") == 15
    assert _extract_historical_years("best stocks 0 year", default=7) == 1
    assert _extract_historical_years("no period here", default=7) == 7


def test_extract_index_history_targets_matches_aliases_and_broad_query():
    assert _extract_index_history_targets("compare nasdaq100 and sp500") == ["NASDAQ_100", "SP500"]
    assert _extract_index_history_targets("us index historical return") == ["NASDAQ_100", "SP500", "NASDAQ_COMPOSITE"]


def test_broad_stock_history_query_excludes_crypto():
    assert _is_broad_stock_history_query("stock market historical return 10 year") is True
    assert _is_broad_stock_history_query("crypto historical return 10 year") is False


def test_capability_question_detects_direct_and_soft_phrasing():
    assert _is_capability_question("can you compare stock returns?") is True
    assert _is_capability_question("market data ?") is True
    assert _is_capability_question("plain statement only") is False


def test_stock_top_performer_history_question_detects_ranking():
    assert _is_stock_top_performer_history_question("top 10 best performing stocks historical 10 year") is True
    assert _is_stock_top_performer_history_question("top 10 crypto historical 10 year") is False


def test_extract_stock_history_direction_and_universe():
    assert _extract_stock_history_direction("worst performing stocks over 10 year") == "bottom"
    assert _extract_stock_history_direction("best performing stocks over 10 year") == "top"
    assert _extract_stock_history_universe("nasdaq 100 top stocks") == "NASDAQ100"
    assert _extract_stock_history_universe("sp500 best stocks") == "SP500"
    assert _extract_stock_history_universe("best us stocks") == "COMBINED"


def test_ranked_stock_history_queries_require_stock_ranking_and_period():
    assert _is_ranked_stock_history_query("top 10 stock returns over 5 year history") is True
    assert _is_ranked_stock_history_query("top 10 crypto returns over 5 year history") is False
    assert _is_explicit_stock_ranking_request("top 10 stock returns over 5 year history") is True
    assert _is_explicit_stock_ranking_request("stock ranking without period") is False
