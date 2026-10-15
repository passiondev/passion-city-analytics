-- One row per person's membership in a group (a person in three groups has
-- three rows). Join to dim_person on person_key and to dim_group on group_key.
--
-- Rock stores group memberships against a person id directly, so no alias
-- lookup is needed here.

with members as (

    select * from {{ ref('stg_rock__group_members') }}

)

select
    farm_fingerprint(cast(group_member_id as string))       as group_member_key,
    group_member_id,

    farm_fingerprint(cast(person_id as string))             as person_key,
    farm_fingerprint(cast(group_id as string))              as group_key,
    group_role_id,

    group_member_status,
    is_archived,
    is_currently_active_member,

    cast(format_date('%Y%m%d', date(added_at)) as int64)    as added_date_key,
    added_at,
    inactive_at,
    archived_at,

    updated_at

from members
