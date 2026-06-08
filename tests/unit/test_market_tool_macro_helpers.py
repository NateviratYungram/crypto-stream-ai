from intelligence.tools.market_tool_macro_helpers import (
    _build_market_climate_response,
    _build_market_regime_response,
    _build_risk_parameters_response,
    _build_sector_rotation_response,
)


def test_build_sector_rotation_response_orders_and_summarizes():
    response = _build_sector_rotation_response(
        {
            "Technology (XLK)": 4.2,
            "Energy (XLE)": -1.0,
            "Utilities (XLU)": 1.5,
            "Financials (XLF)": 0.5,
        }
    )

    assert response["leading_sectors"][0][0] == "Technology (XLK)"
    assert response["lagging_sectors"][-1][0] == "Energy (XLE)"
    assert response["market_summary"] == "Institutional flow favors Technology (XLK)"


def test_build_sector_rotation_response_handles_empty_perf():
    response = _build_sector_rotation_response({})

    assert response["leading_sectors"] == []
    assert response["market_summary"] == "Neutral"


def test_build_risk_parameters_response_returns_error_for_flat_trade():
    assert _build_risk_parameters_response(
        account_size=10_000,
        entry=100,
        stop_loss=100,
        risk_pct=1.0,
    ) == {"error": "Entry and Stop Loss cannot be the same price."}


def test_build_risk_parameters_response_builds_long_and_short_targets():
    long_trade = _build_risk_parameters_response(
        account_size=10_000,
        entry=100,
        stop_loss=95,
        risk_pct=2.0,
    )
    short_trade = _build_risk_parameters_response(
        account_size=10_000,
        entry=95,
        stop_loss=100,
        risk_pct=1.0,
    )

    assert long_trade["risk_amount_dollars"] == 200.0
    assert long_trade["position_size"] == 40.0
    assert long_trade["suggested_tp_1_2"] == 110
    assert short_trade["suggested_tp_1_2"] == 85


def test_build_market_climate_response_classifies_regimes():
    risk_on = _build_market_climate_response(12.0, 96.0, 3.1)
    risk_off = _build_market_climate_response(24.0, 103.0, 4.3)
    extreme = _build_market_climate_response(35.0, 106.0, 5.1)

    assert risk_on["regime"] == "RISK ON"
    assert risk_on["threat_level"] == "OPTIMAL"
    assert risk_off["regime"] == "RISK OFF"
    assert extreme["regime"] == "EXTREME TURBULENCE"
    assert "Vol:" in extreme["summary"]


def test_build_market_climate_response_handles_neutral_boundary():
    neutral = _build_market_climate_response(17.5, 100.0, 4.0)

    assert neutral["regime"] == "NEUTRAL"
    assert neutral["threat_level"] == "LOW"
    assert neutral["color"] == "emerald"


def test_build_market_regime_response_formats_optional_fields_and_defaults():
    response = _build_market_regime_response(
        regime_date=None,
        regime="UNKNOWN",
        confidence=42.0,
        drivers=None,
        sp500_vol=None,
        crypto_vol=None,
        btc_corr=None,
        sp500_ma=None,
        btc_ma=None,
    )

    assert response["as_of"] is None
    assert response["regime_emoji"] == "NEUTRAL"
    assert response["drivers"] == []
    assert response["market_stress"] == {
        "sp500_vol_30d_annualized": "N/A",
        "crypto_vol_30d_annualized": "N/A",
        "btc_sp500_correlation_30d": "N/A",
    }
    assert response["trend_context"] == {
        "sp500_vs_200ma": "N/A",
        "btc_vs_200ma": "N/A",
    }
    assert "Key drivers:" not in response["interpretation"]
    assert "BTC/SP500 correlation" not in response["interpretation"]


def test_build_market_regime_response_uses_custom_emoji_and_driver_context():
    response = _build_market_regime_response(
        regime_date="2026-06-05",
        regime="RISK_ON",
        confidence=88.6,
        drivers=["Liquidity expansion", "Falling yields"],
        sp500_vol=0.12,
        crypto_vol=0.45,
        btc_corr=0.34,
        sp500_ma=0.08,
        btc_ma=-0.03,
        emoji_map={"RISK_ON": "GREEN"},
    )

    assert response["regime_emoji"] == "GREEN"
    assert response["confidence"] == "89%"
    assert response["market_stress"] == {
        "sp500_vol_30d_annualized": "12.0%",
        "crypto_vol_30d_annualized": "45.0%",
        "btc_sp500_correlation_30d": "0.34",
    }
    assert response["trend_context"] == {
        "sp500_vs_200ma": "8.0%",
        "btc_vs_200ma": "-3.0%",
    }
    assert "SP500 is above its 200MA." in response["interpretation"]
    assert "BTC/SP500 correlation is 0.34 (30d)." in response["interpretation"]
    assert "Key drivers: Liquidity expansion, Falling yields." in response["interpretation"]
