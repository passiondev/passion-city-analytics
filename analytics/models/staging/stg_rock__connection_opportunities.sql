with source as (

    select * from {{ source('rock', 'rock_connection_opportunities') }}

),

renamed as (

    select
        -- keys
        Id                                                  as connection_opportunity_id,
        Guid                                                as connection_opportunity_guid,
        ConnectionTypeId                                    as connection_type_id,

        -- descriptive
        Name                                                as name,
        PublicName                                          as public_name,
        Description                                         as description,
        Summary                                             as summary,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- how long a request on this opportunity has before it is flagged.
        -- Rock uses these to set due_date and due_soon_date on each request.
        RequestDueDateOffsetInDays                          as request_due_date_offset_days,
        RequestDueSoonOffsetInDays                          as request_due_soon_offset_days,

        -- flags. Cast through int64 so this works whether the bronze column
        -- landed as BOOL, INT64, or FLOAT64.
        cast(cast(IsActive as int64) as bool)               as is_active,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- PhotoId, IconCssClass, the Show... display switches, and
        -- AdditionalSettingsJson are presentation and configuration, so
        -- they stay in bronze.

    from source

)

select * from renamed
