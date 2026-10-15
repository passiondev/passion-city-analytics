with source as (

    select * from {{ source('rock', 'rock_group_members') }}

),

renamed as (

    select
        -- keys
        Id                                                  as group_member_id,
        Guid                                                as group_member_guid,
        GroupId                                             as group_id,
        PersonId                                            as person_id,
        GroupRoleId                                         as group_role_id,
        GroupTypeId                                         as group_type_id,
        ScheduleTemplateId                                  as schedule_template_id,

        -- status (raw code, decoded below)
        GroupMemberStatus                                   as group_member_status_code,

        -- membership details
        GuestCount                                          as guest_count,
        GroupOrder                                          as group_order,
        CommunicationPreference                             as communication_preference_code,
        ScheduleStartDate                                   as schedule_start_date,
        ScheduleReminderEmailOffsetDays                     as schedule_reminder_email_offset_days,

        -- flags (raw)
        cast(cast(IsSystem as int64) as bool)               as is_system,
        cast(cast(IsNotified as int64) as bool)             as is_notified,
        cast(cast(IsArchived as int64) as bool)             as is_archived,
        cast(cast(IsChatMuted as int64) as bool)            as is_chat_muted,
        cast(cast(IsChatBanned as int64) as bool)           as is_chat_banned,

        -- when
        DateTimeAdded                                       as added_at,
        InactiveDateTime                                    as inactive_at,
        ArchivedDateTime                                    as archived_at,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- Note is deliberately left out: it is free text entered by group
        -- leaders and can hold sensitive personal detail, so it stays in
        -- bronze only.

    from source

),

final as (

    select
        *,

        -- Rock's GroupMemberStatus enum: 0 = Inactive, 1 = Active,
        -- 2 = Pending. Confirm against your Rock version before relying on
        -- this in reports.
        case group_member_status_code
            when 0 then 'Inactive'
            when 1 then 'Active'
            when 2 then 'Pending'
            else 'Unknown'
        end                                                 as group_member_status,

        -- Business logic: a membership only counts as current when the
        -- member is Active AND the row is not archived. Rock can leave an
        -- archived membership with an Active status, so use this field, not
        -- the status alone, when filtering to current members. Mirrors
        -- is_currently_active on stg_rock__groups.
        coalesce(
            group_member_status_code = 1 and not coalesce(is_archived, false),
            false
        )                                                   as is_currently_active_member

    from renamed

)

select * from final
