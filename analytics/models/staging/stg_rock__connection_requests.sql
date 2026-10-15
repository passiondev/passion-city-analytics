with source as (

    select * from {{ source('rock', 'rock_connection_requests') }}

),

renamed as (

    select
        -- keys
        Id                                                  as connection_request_id,
        Guid                                                as connection_request_guid,
        ConnectionOpportunityId                             as connection_opportunity_id,
        ConnectionTypeId                                    as connection_type_id,
        ConnectionTypeSourceId                              as connection_type_source_id,
        ConnectionStatusId                                  as connection_status_id,
        PersonAliasId                                       as person_alias_id,
        ConnectorPersonAliasId                              as connector_person_alias_id,
        CampusId                                            as campus_id,
        AssignedGroupId                                     as assigned_group_id,
        AssignedGroupMemberRoleId                           as assigned_group_member_role_id,
        AssignedGroupMemberStatus                           as assigned_group_member_status_code,

        -- state (raw code, decoded below)
        ConnectionState                                     as connection_state_code,

        -- ordering. Order is a reserved word in BigQuery, so it is quoted.
        `Order`                                             as sort_order,

        -- when
        FollowupDate                                        as followup_at,
        date(DueDate)                                       as due_date,
        date(DueSoonDate)                                   as due_soon_date,
        ConnectedDateTime                                   as connected_at,
        CreatedDateKey                                      as created_date_key,

        cast(cast(WasCompletedOnTime as int64) as bool)     as was_completed_on_time,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- Comments is deliberately left out: it is free text from people
        -- working a request and can hold sensitive personal detail, so it
        -- stays in bronze only. AssignedGroupMemberAttributeValues is
        -- serialized plumbing and also stays in bronze.

    from source

),

final as (

    select
        *,

        -- Rock's ConnectionState enum: 0 = Active, 1 = Inactive,
        -- 2 = Future Follow-up, 3 = Connected. Confirm against your Rock
        -- version before relying on this in reports.
        case connection_state_code
            when 0 then 'Active'
            when 1 then 'Inactive'
            when 2 then 'Future Follow-up'
            when 3 then 'Connected'
            else 'Unknown'
        end                                                 as connection_state,

        coalesce(connection_state_code = 3, false)          as is_connected,

        -- Whole days from creation to connection. Null until a request is
        -- connected, so averages only include requests that finished.
        case
            when connected_at is not null
                then timestamp_diff(connected_at, created_at, day)
        end                                                 as days_to_connect

    from renamed

)

select * from final
