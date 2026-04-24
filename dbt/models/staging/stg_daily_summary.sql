with source as (
    select * from {{ source('crypto_stream', 'daily_summary') }}
),

enriched as (
    select
        report_date,
        symbol,
        open_price,
        high_price,
        low_price,
        close_price,
        total_volume,
        trade_count,
        whale_count,
        whale_volume,
        round(close_price - open_price, 8)                                      as price_change,
        round((close_price - open_price) / nullif(open_price, 0) * 100, 4)      as price_change_pct,
        round(whale_volume / nullif(total_volume, 0) * 100, 2)                  as whale_volume_pct,
        round(whale_count::numeric / nullif(trade_count, 0) * 100, 2)           as whale_trade_pct,
        created_at
    from source
)

select * from enriched
