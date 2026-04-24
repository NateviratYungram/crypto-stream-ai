with source as (
    select * from {{ source('crypto_stream', 'enriched_trades') }}
),

renamed as (
    select
        trade_id,
        symbol,
        price,
        quantity,
        to_timestamp(timestamp / 1000.0) at time zone 'UTC'  as traded_at,
        is_buyer_maker,
        is_whale,
        ingestion_time
    from source
)

select * from renamed
