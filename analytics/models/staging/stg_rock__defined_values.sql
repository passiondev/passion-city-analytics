with source as (

    select * from {{ source('rock', 'rock_defined_values') }}

),

renamed as (

    select
        -- keys. Defined value ids are unique across every defined type, so
        -- decoding a ...ValueId column only needs a join on defined_value_id.
        Id                                                  as defined_value_id,
        Guid                                                as defined_value_guid,
        DefinedTypeId                                       as defined_type_id,
        CategoryId                                          as category_id,

        -- the label people see in Rock
        Value                                               as value,
        Description                                         as description,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- flags. Cast through int64 so this works whether the bronze column
        -- landed as BOOL, INT64, or FLOAT64.
        cast(cast(IsActive as int64) as bool)               as is_active,
        cast(cast(IsSystem as int64) as bool)               as is_system,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

    from source

)

select * from renamed
