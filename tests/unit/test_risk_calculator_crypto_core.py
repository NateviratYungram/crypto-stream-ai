from intelligence.risk_calculator_crypto import (
    calculate_crypto_risk,
    calculate_position_scenarios,
    get_risk_advice_thai,
)


def test_calculate_crypto_risk_rejects_invalid_inputs():
    assert calculate_crypto_risk(0, 90, 1000)["error"] == "Invalid entry price or balance"
    assert calculate_crypto_risk(100, 100, 1000)["error"] == "Stop loss equals entry price"


def test_calculate_crypto_risk_builds_long_position():
    risk = calculate_crypto_risk(100.0, 95.0, 1000.0, risk_percent=1.0, leverage=5.0)

    assert risk["direction"] == "LONG"
    assert risk["risk_usdt"] == 10.0
    assert risk["position_size_units"] == 2.0
    assert risk["position_value_usdt"] == 200.0
    assert risk["margin_required_usdt"] == 40.0
    assert risk["risk_level"] == "LOW"
    assert risk["trades_to_wipeout"] == 100


def test_calculate_crypto_risk_builds_short_position_and_risk_levels():
    medium = calculate_crypto_risk(100.0, 105.0, 1000.0, risk_percent=2.0)
    high = calculate_crypto_risk(100.0, 110.0, 1000.0, risk_percent=5.0)
    extreme = calculate_crypto_risk(100.0, 120.0, 1000.0, risk_percent=6.0)

    assert medium["direction"] == "SHORT"
    assert medium["risk_level"] == "MEDIUM"
    assert high["risk_level"] == "HIGH"
    assert extreme["risk_level"] == "EXTREME"


def test_get_risk_advice_thai_returns_branch_specific_text():
    low = calculate_crypto_risk(100, 95, 1000, risk_percent=1.0)
    medium = calculate_crypto_risk(100, 95, 1000, risk_percent=2.0)
    high = calculate_crypto_risk(100, 95, 1000, risk_percent=5.0)
    extreme = calculate_crypto_risk(100, 95, 1000, risk_percent=6.0)

    assert "$10.00" in get_risk_advice_thai(low)
    assert "$100" in get_risk_advice_thai(medium)
    assert "5.0%" in get_risk_advice_thai(high)
    assert "6.0%" in get_risk_advice_thai(extreme)


def test_calculate_position_scenarios_skips_invalid_calculations():
    scenarios = calculate_position_scenarios(100.0, 95.0, 1000.0, leverage=2.0)
    invalid = calculate_position_scenarios(100.0, 100.0, 1000.0)

    assert len(scenarios) == 6
    assert [row["risk_percent"] for row in scenarios] == [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]
    assert scenarios[0]["risk_level"] == "LOW"
    assert scenarios[-1]["risk_level"] == "HIGH"
    assert invalid == []
