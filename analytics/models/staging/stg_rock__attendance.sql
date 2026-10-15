with source as (

    select * from {{ source('rock', 'rock_attendance') }}

),

renamed as (

    select
        -- keys
        Id                                                  as attendance_id,
        Guid                                                as attendance_guid,
        OccurrenceId                                        as occurrence_id,
        PersonAliasId                                       as person_alias_id,
        CampusId                                            as campus_id,
        DeviceId                                            as device_id,
        AttendanceCodeId                                    as attendance_code_id,
        AttendanceCheckInSessionId                          as attendance_check_in_session_id,
        SearchResultGroupId                                 as search_result_group_id,
        SearchTypeValueId                                   as search_type_value_id,
        QualifierValueId                                    as qualifier_value_id,
        SourceValueId                                       as source_value_id,
        DeclineReasonValueId                                as decline_reason_value_id,

        -- who did what
        CheckedInByPersonAliasId                            as checked_in_by_person_alias_id,
        CheckedOutByPersonAliasId                           as checked_out_by_person_alias_id,
        PresentByPersonAliasId                              as present_by_person_alias_id,
        ScheduledByPersonAliasId                            as scheduled_by_person_alias_id,

        -- when
        StartDateTime                                       as started_at,
        EndDateTime                                         as ended_at,
        PresentDateTime                                     as present_at,
        RSVPDateTime                                        as rsvp_at,

        -- flags (raw)
        cast(cast(DidAttend as int64) as bool)                             as did_attend,
        cast(cast(IsFirstTime as int64) as bool)                           as is_first_time,
        cast(cast(Processed as int64) as bool)                             as is_processed,
        cast(cast(ScheduledToAttend as int64) as bool)                     as is_scheduled_to_attend,
        cast(cast(RequestedToAttend as int64) as bool)                     as is_requested_to_attend,
        cast(cast(ScheduleConfirmationSent as int64) as bool)              as is_schedule_confirmation_sent,
        cast(cast(ScheduleReminderSent as int64) as bool)                  as is_schedule_reminder_sent,

        -- raw codes (decoded below where the meaning is known)
        RSVP                                                as rsvp_code,
        CheckInStatus                                       as check_in_status_code,

        Note                                                as note,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- SearchValue is deliberately left out: it holds whatever was typed
        -- at check-in to find a person (often a phone number), so it stays
        -- in bronze only.

    from source

),

final as (

    select
        * except (did_attend),

        -- Business logic: Rock creates attendance rows for people who were
        -- only scheduled or RSVP'd, not just people who showed up. did_attend
        -- is the flag for actually being there; treat null as "did not
        -- attend" so downstream counts never silently drop rows.
        coalesce(did_attend, false)                         as did_attend,

        -- Rock's RSVP enum: 0 = Unknown, 1 = Yes, 2 = No, 3 = Maybe.
        -- Confirm against your Rock version before relying on this in reports.
        case rsvp_code
            when 1 then 'Yes'
            when 2 then 'No'
            when 3 then 'Maybe'
            else 'Unknown'
        end                                                 as rsvp

    from renamed

)

select * from final
