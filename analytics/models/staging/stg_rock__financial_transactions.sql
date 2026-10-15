with source as (

    select * from {{ source('rock', 'rock_financial_transactions') }}

),

renamed as (

    select
        -- keys
        Id                                                  as financial_transaction_id,
        Guid                                                as financial_transaction_guid,
        BatchId                                             as batch_id,
        ScheduledTransactionId                              as scheduled_transaction_id,
        FinancialGatewayId                                  as financial_gateway_id,
        FinancialPaymentDetailId                            as financial_payment_detail_id,
        SettledGroupId                                      as settled_group_id,

        -- who. AuthorizedPersonAliasId is the giver; it points at Rock's
        -- PersonAlias table, not directly at a person.
        AuthorizedPersonAliasId                             as authorized_person_alias_id,
        ProcessedByPersonAliasId                            as processed_by_person_alias_id,

        -- what kind (raw DefinedValue ids; decode once DefinedValue is loaded)
        TransactionTypeValueId                              as transaction_type_value_id,
        SourceTypeValueId                                   as source_type_value_id,
        NonCashAssetTypeValueId                             as non_cash_asset_type_value_id,
        ForeignCurrencyCodeValueId                          as foreign_currency_code_value_id,

        -- gateway result
        TransactionCode                                     as transaction_code,
        Status                                              as status,
        StatusMessage                                       as status_message,

        -- when. Rock stores these as local time with no time zone, and the
        -- load treats them as UTC, so date() returns the same calendar date
        -- you see in Rock.
        TransactionDateTime                                 as transaction_at,
        date(TransactionDateTime)                           as transaction_date,
        date(SundayDate)                                    as sunday_date,
        TransactionDateKey                                  as transaction_date_key,
        ProcessedDateTime                                   as processed_at,
        SettledDate                                         as settled_at,
        SettledDateKey                                      as settled_date_key,
        FutureProcessingDateTime                            as future_processing_at,

        -- flags (raw). Cast through int64 so this works whether the bronze
        -- column landed as BOOL, INT64, or FLOAT64.
        cast(cast(IsSettled as int64) as bool)              as is_settled,
        cast(cast(IsReconciled as int64) as bool)           as is_reconciled,
        cast(cast(ShowAsAnonymous as int64) as bool)        as show_as_anonymous,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- Deliberately left out and kept in bronze only: CheckMicrEncrypted,
        -- CheckMicrHash, CheckMicrParts (bank account data from checks) and
        -- Summary (free text). MICRStatus is also left out since it only
        -- describes those check fields.

    from source

)

select * from renamed
