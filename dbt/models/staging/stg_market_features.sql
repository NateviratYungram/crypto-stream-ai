with source as (
    select * from {{ source('crypto_stream', 'market_features') }}
)

select * from source
