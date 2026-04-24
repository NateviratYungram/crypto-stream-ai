-- Daily whale trading summary with buy/sell flow breakdown.
-- Use this for: "Are whales accumulating or distributing BTC?"
-- A positive net_flow means whale buys > sells that day (accumulation signal).
with whale_trades as (
    select * from {{ ref('stg_enriched_trades') }}
    where is_whale = true
),

daily_agg as (
    select
        date_trunc('day', traded_at)::date  as trade_date,
        symbol,
        count(*)                            as whale_trades,
        sum(quantity)                       as whale_volume,
        avg(price)                          as avg_whale_price,
        -- Taker side: is_buyer_maker=false means a buy order hit the ask (aggressive buy)
        sum(case when not is_buyer_maker then quantity else 0 end)  as buy_volume,
        sum(case when is_buyer_maker     then quantity else 0 end)  as sell_volume
    from whale_trades
    group by 1, 2
),

with_flow as (
    select
        trade_date,
        symbol,
        whale_trades,
        whale_volume,
        avg_whale_price,
        buy_volume,
        sell_volume,
        buy_volume - sell_volume                                    as net_flow,
        round(buy_volume / nullif(whale_volume, 0) * 100, 2)       as buy_pct,
        case
            when buy_volume > sell_volume * 1.2 then 'ACCUMULATING'
            when sell_volume > buy_volume * 1.2 then 'DISTRIBUTING'
            else 'NEUTRAL'
        end                                                         as whale_bias
    from daily_agg
)

select * from with_flow
order by trade_date desc, whale_volume desc
