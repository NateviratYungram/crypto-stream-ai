-- Cross-asset daily snapshot: crypto performance alongside macro context.
-- Use this for: "How does BTC behave when the Fed raises rates? When gold rises?"
-- Joins BTC on-chain data (whale trades) with market prices and macro indicators.
with btc_summary as (
    select
        report_date,
        close_price         as btc_close,
        price_change_pct    as btc_return_pct,
        total_volume        as btc_volume,
        whale_volume_pct    as btc_whale_pct,
        whale_trade_pct     as btc_whale_trade_pct
    from {{ ref('stg_daily_summary') }}
    where symbol = 'BTCUSDT'
),

-- Pivot multi-asset OHLCV into one row per day
asset_prices as (
    select
        candle_open_at::date                                            as price_date,
        max(close) filter (where symbol = 'GC=F')                      as gold_close,
        max(close) filter (where symbol = '^GSPC')                     as sp500_close,
        max(close) filter (where symbol = 'CL=F')                      as oil_close,
        max(close) filter (where symbol = 'BTC-USD')                   as btc_usd_close,
        max(close) filter (where symbol = 'ETH-USD')                   as eth_close,
        max(close) filter (where symbol = 'SOL-USD')                   as sol_close,
        max(close) filter (where symbol = '^VIX')                      as vix_close
    from {{ ref('stg_market_ohlcv') }}
    where timeframe = '1d'
      and symbol in ('GC=F', '^GSPC', 'CL=F', 'BTC-USD', 'ETH-USD', 'SOL-USD', '^VIX')
    group by 1
),

-- Pivot FRED macro indicators into one row per date
macro as (
    select
        date,
        max(value) filter (where series_id = 'DFF')         as fed_funds_rate,
        max(value) filter (where series_id = 'T10Y2Y')      as yield_curve_spread,
        max(value) filter (where series_id = 'CPIAUCSL')    as cpi,
        max(value) filter (where series_id = 'UNRATE')      as unemployment_rate
    from {{ ref('stg_macro_indicators') }}
    group by 1
),

final as (
    select
        p.price_date,
        -- BTC on-chain + price
        b.btc_close,
        b.btc_return_pct,
        b.btc_volume,
        b.btc_whale_pct,
        b.btc_whale_trade_pct,
        -- Market prices
        p.gold_close,
        p.sp500_close,
        p.oil_close,
        p.eth_close,
        p.sol_close,
        p.vix_close,
        -- Macro indicators (forward-filled from monthly/quarterly releases)
        m.fed_funds_rate,
        m.yield_curve_spread,
        m.cpi,
        m.unemployment_rate
    from asset_prices p
    left join btc_summary b  on p.price_date = b.report_date
    left join macro m        on p.price_date = m.date
)

select * from final
order by price_date desc
