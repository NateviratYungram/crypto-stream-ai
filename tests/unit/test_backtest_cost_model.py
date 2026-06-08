import pandas as pd

from intelligence.backtest_crypto import simulate_trades


def _two_bar_take_profit_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Close": 100.0,
                "High": 100.0,
                "Low": 100.0,
                "atr_14": 1.0,
                "adx_14": 20.0,
                "signal": 1,
                "regime": "TRENDING",
            },
            {
                "Close": 103.0,
                "High": 104.0,
                "Low": 102.5,
                "atr_14": 1.0,
                "adx_14": 20.0,
                "signal": 0,
                "regime": "TRENDING",
            },
        ]
    )


def test_backtest_costs_reduce_realized_profit():
    frame = _two_bar_take_profit_frame()

    no_cost = simulate_trades(
        frame,
        initial_balance=100.0,
        risk_pct=1.0,
        partial_tp=False,
        use_trailing_stop=False,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    with_cost = simulate_trades(
        frame,
        initial_balance=100.0,
        risk_pct=1.0,
        partial_tp=False,
        use_trailing_stop=False,
        fee_bps=10.0,
        slippage_bps=10.0,
    )

    assert no_cost["status"] == "success"
    assert with_cost["status"] == "success"
    assert with_cost["net_profit"] < no_cost["net_profit"]
    assert with_cost["cost_model"] == {"fee_bps": 10.0, "slippage_bps": 10.0}
