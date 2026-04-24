with source as (
    select * from {{ source('crypto_stream', 'macro_indicators') }}
),

renamed as (
    select
        series_id,
        series_name,
        date,
        value,
        fetched_at
    from source
)

select * from renamed
