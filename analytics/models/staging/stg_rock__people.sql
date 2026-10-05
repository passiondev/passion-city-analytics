with source as (

    select * from {{ source('rock', 'rock_people') }}

),

renamed as (

    select
        -- keys
        Id                                                  as person_id,
        Guid                                                as person_guid,
        PrimaryFamilyId                                     as primary_family_id,
        PrimaryCampusId                                     as primary_campus_id,
        GivingId                                            as giving_id,

        -- names
        FirstName                                           as first_name,
        NickName                                            as nick_name,
        MiddleName                                          as middle_name,
        LastName                                            as last_name,

        -- demographics
        BirthDay                                            as birth_day,
        BirthMonth                                          as birth_month,
        BirthYear                                           as birth_year,
        Gender                                               as gender_code,
        MaritalStatusValueId                                as marital_status_value_id,

        -- contact
        Email                                               as email,
        cast(IsEmailActive as bool)                         as is_email_active,
        EmailPreference                                     as email_preference_code,

        -- status / lifecycle (raw codes, decoded below)
        RecordTypeValueId                                   as record_type_value_id,
        RecordStatusValueId                                 as record_status_value_id,
        ConnectionStatusValueId                             as connection_status_value_id,
        cast(IsDeceased as bool)                            as is_deceased,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

    from source

),

final as (

    select
        person_id,
        person_guid,
        primary_family_id,
        primary_campus_id,
        giving_id,

        first_name,
        coalesce(nick_name, first_name)                     as display_name,
        middle_name,
        last_name,
        concat(coalesce(nick_name, first_name), ' ', last_name) as full_name,

        -- Business logic: reconstruct a birth_date only when all three
        -- components are present; Rock allows partial birth dates (e.g.
        -- month/day only, no year) which cannot form a valid date.
        case
            when birth_year is not null
                and birth_month is not null
                and birth_day is not null
            then date(cast(birth_year as int64), cast(birth_month as int64), cast(birth_day as int64))
        end                                                  as birth_date,
        birth_day,
        birth_month,
        birth_year,

        case gender_code
            when 1 then 'Male'
            when 2 then 'Female'
            else 'Unknown'
        end                                                  as gender,

        marital_status_value_id,

        email,
        is_email_active,
        case email_preference_code
            when 0 then 'Email Allowed'
            when 1 then 'No Mass Emails'
            when 2 then 'Do Not Email'
            else 'Unknown'
        end                                                  as email_preference,

        record_type_value_id,
        record_status_value_id,
        connection_status_value_id,
        is_deceased,

        -- Business logic: a person is considered "active" only if their
        -- record status is Active AND they are not marked deceased.
        -- NOTE: replace the hardcoded id below with your Rock instance's
        -- actual DefinedValue.Id for RecordStatus = "Active" (check
        -- dbo.DefinedValue where DefinedTypeId corresponds to Record Status).
        case
            when record_status_value_id = {{ var('rock_record_status_active_id', 3) }}
                and not is_deceased
            then true
            else false
        end                                                  as is_active,

        created_at,
        updated_at,
        _bronze_loaded_at

    from renamed

)

select * from final
