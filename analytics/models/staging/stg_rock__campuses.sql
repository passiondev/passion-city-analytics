with source as (

    select * from {{ source('rock', 'rock_campuses') }}

),

renamed as (

    select
        -- keys
        Id                                                  as campus_id,
        Guid                                                as campus_guid,
        LocationId                                          as location_id,
        LeaderPersonAliasId                                 as leader_person_alias_id,
        TeamGroupId                                         as team_group_id,
        CampusStatusValueId                                 as campus_status_value_id,
        CampusTypeValueId                                   as campus_type_value_id,

        -- descriptive
        Name                                                as name,
        ShortCode                                           as short_code,
        Description                                         as description,
        Url                                                 as url,
        ServiceTimes                                        as service_times,
        TimeZoneId                                          as time_zone_id,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- size and giving measures. TitheMetric is cast to NUMERIC (exact
        -- decimal) so a stray FLOAT64 in bronze never leaks rounding error.
        AverageWeekendAttendance                            as average_weekend_attendance,
        cast(TitheMetric as numeric)                        as tithe_metric,

        -- flags. Cast through int64 so this works whether the bronze column
        -- landed as BOOL, INT64, or FLOAT64.
        cast(cast(IsActive as int64) as bool)               as is_active,
        cast(cast(IsSystem as int64) as bool)               as is_system,

        -- dates. These land in bronze as either DATE or TIMESTAMP depending
        -- on how the table was loaded; date() accepts both.
        date(OpenedDate)                                    as opened_date,
        date(ClosedDate)                                    as closed_date,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- PhoneNumber, BeaconId, and the Foreign* columns stay in bronze.

    from source

),

final as (

    select
        *,

        -- Business logic: a campus is only open when it is marked active AND
        -- today falls between its opened and closed dates. Rock can leave a
        -- closed campus flagged active, so use this field, not is_active
        -- alone, when listing campuses currently in operation. Evaluated
        -- when queried, so it stays correct as dates pass.
        coalesce(
            is_active
            and (opened_date is null or opened_date <= current_date())
            and (closed_date is null or closed_date > current_date()),
            false
        )                                                   as is_currently_open

    from renamed

)

select * from final
