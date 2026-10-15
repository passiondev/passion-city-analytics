with source as (

    select * from {{ source('rock', 'rock_financial_transaction_details') }}

),

renamed as (

    select
        -- keys
        Id                                                  as financial_transaction_detail_id,
        Guid                                                as financial_transaction_detail_guid,
        TransactionId                                       as financial_transaction_id,
        AccountId                                           as financial_account_id,

        -- optional link to the thing the gift was for (event, group, and so on)
        EntityTypeId                                        as entity_type_id,
        EntityId                                            as entity_id,

        -- money. Cast to NUMERIC (exact decimal) so a stray FLOAT64 or STRING
        -- column in bronze never leaks floating point error into totals.
        cast(Amount as numeric)                             as amount,
        cast(FeeAmount as numeric)                          as fee_amount,
        cast(FeeCoverageAmount as numeric)                  as fee_coverage_amount,
        cast(ForeignCurrencyAmount as numeric)              as foreign_currency_amount,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- Summary is deliberately left out: it is free text and stays in
        -- bronze only.

    from source

),

final as (

    select
        *,

        -- Business logic: Rock records refunds and reversals as negative
        -- amounts on the same table as gifts. Flagging them here keeps
        -- downstream "total given" logic from treating a refund as a gift.
        coalesce(amount < 0, false)                         as is_refund

    from renamed

)

select * from final
