-- One row per group in Rock, current state only, with the group type and
-- campus names decoded.
--
-- is_door_holder_team and is_connect_group come from the group type ids below.
-- They default to your Rock instance's ids and can be changed in one place by
-- setting these vars in dbt_project.yml:
--     door_holder_group_type_id    (default 34)
--     connect_group_group_type_id  (default 38)

with group_rows as (

    select * from {{ ref('stg_rock__groups') }}

),

group_types as (

    select group_type_id, name as group_type_name
    from {{ ref('stg_rock__group_types') }}

),

campuses as (

    select campus_id, name as campus_name
    from {{ ref('stg_rock__campuses') }}

)

select
    -- surrogate key generated in the warehouse; group_id is Rock's own id
    farm_fingerprint(cast(g.group_id as string))            as group_key,
    g.group_id,
    g.group_guid,

    g.name,
    g.parent_group_id,

    g.group_type_id,
    gt.group_type_name,

    g.campus_id,
    c.campus_name,

    -- Which groups the door holder report cares about
    coalesce(g.group_type_id = {{ var('door_holder_group_type_id', 34) }}, false)
                                                            as is_door_holder_team,
    coalesce(g.group_type_id = {{ var('connect_group_group_type_id', 38) }}, false)
                                                            as is_connect_group,

    g.is_security_role,
    g.is_active,
    g.is_archived,
    g.is_currently_active,

    g.created_at,
    g.updated_at

from group_rows g
left join group_types gt
    on gt.group_type_id = g.group_type_id
left join campuses c
    on c.campus_id = g.campus_id
