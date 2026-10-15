with source as (

    select * from {{ source('rock', 'rock_attendance_occurrences') }}

),

renamed as (

    select
        -- keys
        Id                                                  as occurrence_id,
        Guid                                                as occurrence_guid,
        GroupId                                             as group_id,
        LocationId                                          as location_id,
        ScheduleId                                          as schedule_id,
        StepTypeId                                          as step_type_id,
        AttendanceTypeValueId                               as attendance_type_value_id,
        RootGroupTypeId                                     as root_group_type_id,

        -- when the occurrence took place. These land in bronze as either DATE
        -- or TIMESTAMP depending on how the table was loaded; date() accepts both.
        date(OccurrenceDate)                                as occurrence_date,
        date(SundayDate)                                    as sunday_date,
        OccurrenceDateKey                                   as occurrence_date_key,

        -- descriptive
        Name                                                as name,
        Notes                                               as notes,
        AnonymousAttendanceCount                            as anonymous_attendance_count,

        -- flags (raw)
        cast(cast(DidNotOccur as int64) as bool)                           as did_not_occur,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- Confirmation/decline message text and reminder fields stay in
        -- bronze; they're check-in and scheduling plumbing, not analytics.

    from source

),

final as (

    select
        *,

        -- Business logic: Rock lets someone mark an occurrence as "did not
        -- occur" (e.g. a cancelled service). did_occur is the positive form
        -- so downstream filters read naturally; null is treated as occurred.
        not coalesce(did_not_occur, false)                  as did_occur

    from renamed

)

select * from final
