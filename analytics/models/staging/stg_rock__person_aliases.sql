with source as (

    select * from {{ source('rock', 'rock_person_aliases') }}

),

renamed as (

    select
        -- keys. person_alias_id is the id the other Rock tables store
        -- (attendance, giving, connection requests); person_id is the person
        -- it resolves to today.
        Id                                                  as person_alias_id,
        Guid                                                as person_alias_guid,
        PersonId                                            as person_id,
        AliasPersonId                                       as alias_person_id,
        AliasPersonGuid                                     as alias_person_guid,

        Name                                                as name,

        -- when
        AliasedDateTime                                     as aliased_at,
        LastVisitDateTime                                   as last_visit_at,

        -- ingestion metadata
        _loaded_at                                          as _bronze_loaded_at

        -- InternalMessage is deliberately left out: it is an internal
        -- free-text field and stays in bronze only.

    from source

),

final as (

    select
        *,

        -- Business logic: when two people are merged in Rock, the merged
        -- person's aliases are repointed at the surviving person, so
        -- alias_person_id no longer equals person_id. True here means the
        -- alias came from a merge. This rests on Rock's convention that a
        -- person's own alias has matching ids; spot-check it on a few people
        -- you know were merged before using it in reporting.
        coalesce(alias_person_id != person_id, false)       as is_merged_alias

    from renamed

)

select * from final
