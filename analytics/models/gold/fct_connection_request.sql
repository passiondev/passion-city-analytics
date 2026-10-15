-- One row per connection request. Join to dim_person on person_key (the
-- requester) and, for the person assigned to follow up, connector_person_key.
--
-- Rock stores a person_alias_id on each request, so this model resolves it
-- to a person through stg_rock__person_aliases and stores person_key itself.
--
-- request_category groups requests using your opportunity ids. They default
-- to your Rock instance's ids and can be changed in one place by setting
-- these vars in dbt_project.yml:
--     door_holder_connection_opportunity_id       (default 60)
--     connect_group_connection_opportunity_ids    (default [68, 69])

with requests as (

    select * from {{ ref('stg_rock__connection_requests') }}

),

aliases as (

    select person_alias_id, person_id
    from {{ ref('stg_rock__person_aliases') }}

),

opportunities as (

    select connection_opportunity_id, name as opportunity_name
    from {{ ref('stg_rock__connection_opportunities') }}

)

select
    farm_fingerprint(cast(r.connection_request_id as string))
                                                            as connection_request_key,
    r.connection_request_id,

    -- who. Null when the alias does not resolve to a person.
    farm_fingerprint(cast(requester.person_id as string))   as person_key,
    farm_fingerprint(cast(connector.person_id as string))   as connector_person_key,

    -- what
    r.connection_opportunity_id,
    o.opportunity_name,
    r.connection_type_id,
    case
        when r.connection_opportunity_id = {{ var('door_holder_connection_opportunity_id', 60) }}
            then 'Door Holder'
        when r.connection_opportunity_id in ({{ var('connect_group_connection_opportunity_ids', [68, 69]) | join(', ') }})
            then 'Connect Group'
        else 'Other'
    end                                                     as request_category,

    -- the group the request was assigned to, if any. Lets a request be
    -- matched to the membership it produced.
    farm_fingerprint(cast(r.assigned_group_id as string))   as assigned_group_key,
    r.campus_id,

    -- state
    r.connection_state,
    r.is_connected,
    r.days_to_connect,
    r.due_date,
    r.was_completed_on_time,

    -- when
    r.created_date_key,
    r.created_at,
    cast(format_date('%Y%m%d', date(r.connected_at)) as int64)
                                                            as connected_date_key,
    r.connected_at,

    r.updated_at

from requests r
left join aliases requester
    on requester.person_alias_id = r.person_alias_id
left join aliases connector
    on connector.person_alias_id = r.connector_person_alias_id
left join opportunities o
    on o.connection_opportunity_id = r.connection_opportunity_id
