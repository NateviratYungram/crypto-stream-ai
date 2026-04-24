with source as (
    select * from {{ source('crypto_stream', 'market_ohlcv') }}
),

renamed as (
    select
        symbol,
        timeframe,
        ts                                              as candle_open_at,
        open,
        high,
        low,
        close,
        coalesce(volume, 0)                             as volume,
        source                                          as data_source,
        high - low                                      as candle_range,
        case
            when close > open then 'BULLISH'
            when close < open then 'BEARISH'
            else 'DOJI'
        end                                             as candle_direction,
        fetched_at
    from source
)

select * from renamed
