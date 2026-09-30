with source as (

    select * from {{ source('rock', 'rock_groups') }}

),

renamed as (

    select
        -- keys
        Id                                                  as group_id,
        Guid                                                as group_guid,
        ParentGroupId                                       as parent_group_id,
        GroupTypeId                                         as group_type_id,
        CampusId                                            as campus_id,
        GroupAdministratorPersonAliasId                     as group_administrator_person_alias_id,

        -- descriptive
        Name                                                as name,
        Description                                         as description,

        -- flags (raw)
        cast(IsSecurityRole as bool)                        as is_security_role,
        cast(IsActive as bool)                               as is_active,
        cast(IsArchived as bool)                            as is_archived,
        cast(IsPublic as bool)                              as is_public,
        cast(AllowGuests as bool)                           as allow_guests,

        -- status
        StatusValueId                                       as status_value_id,
        InactiveDateTime                                    as inactive_at,
        ArchivedDateTime                                    as archived_at,

        -- timestamps
        CreatedDateTime                                     as created_at,
        ModifiedDateTime                                    as updated_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

    from source

),

final as (

    select
        group_id,
        group_guid,
        parent_group_id,
        group_type_id,
        campus_id,
        group_administrator_person_alias_id,

        name,
        description,

        is_security_role,
        is_active,
        is_archived,
        is_public,
        allow_guests,

        status_value_id,
        inactive_at,
        archived_at,

        -- Business logic: a group is only truly "usable" if it's marked
        -- active AND hasn't been archived — Rock allows a group to be
        -- IsActive = true while also archived, which downstream reporting
        -- should treat as not active. Use this field, not is_active alone,
        -- when filtering to groups currently in use.
        (is_active and not is_archived)                     as is_currently_active,

        created_at,
        updated_at,
        _bronze_loaded_at

    from renamed

)

select * from final
