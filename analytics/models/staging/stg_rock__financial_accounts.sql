with source as (

    select * from {{ source('rock', 'rock_financial_accounts') }}

),

renamed as (

    select
        -- keys
        Id                                                  as financial_account_id,
        Guid                                                as financial_account_guid,
        ParentAccountId                                     as parent_account_id,
        CampusId                                            as campus_id,
        AccountTypeValueId                                  as account_type_value_id,
        ImageBinaryFileId                                   as image_binary_file_id,

        -- descriptive
        Name                                                as name,
        PublicName                                          as public_name,
        Description                                         as description,
        PublicDescription                                   as public_description,
        GlCode                                              as gl_code,
        Url                                                 as url,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- flags (raw)
        cast(cast(IsActive as int64) as bool)               as is_active,
        cast(cast(IsPublic as int64) as bool)               as is_public,
        cast(cast(IsTaxDeductible as int64) as bool)        as is_tax_deductible,
        cast(cast(UsesCampusChildAccounts as int64) as bool) as uses_campus_child_accounts,

        -- active date range. These land in bronze as either DATE or
        -- TIMESTAMP depending on how the table was loaded; date() accepts both.
        date(StartDate)                                     as start_date,
        date(EndDate)                                       as end_date,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

    from source

),

final as (

    select
        *,

        -- Business logic: an account is only open for giving when it is
        -- marked active AND today falls inside its optional start/end
        -- window. Rock leaves expired accounts flagged active, so use this
        -- field, not is_active alone, when listing funds people can give to.
        -- Evaluated when queried, so it stays correct as dates pass.
        coalesce(
            is_active
            and (start_date is null or start_date <= current_date())
            and (end_date is null or end_date >= current_date()),
            false
        )                                                   as is_currently_active

    from renamed

)

select * from final
