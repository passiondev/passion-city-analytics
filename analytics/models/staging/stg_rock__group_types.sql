with source as (

    select * from {{ source('rock', 'rock_group_types') }}

),

renamed as (

    select
        -- keys
        Id                                                  as group_type_id,
        Guid                                                as group_type_guid,
        InheritedGroupTypeId                                as inherited_group_type_id,
        DefaultGroupRoleId                                  as default_group_role_id,
        GroupTypePurposeValueId                             as group_type_purpose_value_id,
        GroupStatusDefinedTypeId                            as group_status_defined_type_id,

        -- descriptive
        Name                                                as name,
        Description                                         as description,
        GroupTerm                                           as group_term,
        GroupMemberTerm                                     as group_member_term,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- the settings analytics tends to need. Cast through int64 so this
        -- works whether the bronze column landed as BOOL, INT64, or FLOAT64.
        cast(cast(IsSystem as int64) as bool)               as is_system,
        cast(cast(TakesAttendance as int64) as bool)        as takes_attendance,
        cast(cast(ShowInGroupList as int64) as bool)        as show_in_group_list,
        cast(cast(IsSchedulingEnabled as int64) as bool)    as is_scheduling_enabled,
        cast(cast(AttendanceCountsAsWeekendService as int64) as bool)
                                                            as attendance_counts_as_weekend_service,
        cast(cast(EnableGroupHistory as int64) as bool)     as is_group_history_enabled,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- About 70 other columns on this table are Rock configuration
        -- switches (location rules, chat, reminders, peer network, and so
        -- on). They stay in bronze. GroupViewLavaTemplate and
        -- AdditionalSettingsJson hold template code and serialized settings
        -- and are not analytics data.

    from source

)

select * from renamed
