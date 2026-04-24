-- Primary BI table: joins EOD OHLCV with statistical features per symbol per day.
-- Use this for dashboards answering: "What moved today? Who's trending? What's volatile?"
with daily as (
    select * from {{ ref('stg_daily_summary') }}
),

features as (
    select * from {{ ref('stg_market_features') }}
),

regime as (
    select * from {{ source('crypto_stream', 'market_regime') }}
),

final as (
    select
        d.report_date,
        d.symbol,
        -- Price action
        d.open_price,
        d.high_price,
        d.low_price,
        d.close_price,
        d.price_change,
        d.price_change_pct,
        d.total_volume,
        d.trade_count,
        -- Whale activity
        d.whale_count,
        d.whale_volume,
        d.whale_volume_pct,
        d.whale_trade_pct,
        -- Statistical features
        f.return_1d,
        f.return_7d,
        f.return_30d,
        f.return_90d,
        f.volatility_7d,
        f.volatility_30d,
        f.volatility_90d,
        f.corr_vs_sp500_30d,
        f.corr_vs_btc_30d,
        f.beta_vs_sp500,
        f.pct_from_52w_high,
        f.pct_from_52w_low,
        f.rel_strength_30d,
        -- Market context
        r.regime                    as market_regime,
        r.regime_confidence,
        r.sp500_vol_30d,
        r.btc_sp500_corr_30d
    from daily d
    left join features f
        on d.symbol = f.symbol and d.report_date = f.date
    left join regime r
        on d.report_date = r.date
)

select * from final
order by report_date desc, abs(price_change_pct) desc
