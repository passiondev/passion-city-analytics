-- One row per door holder: any person who has ever been a member of a group
-- whose group type is the door holder team type. Carries demographics, how
-- long they have served, whether they are in a connect group, their check-in
-- history, and the history of their door holder join requests.
--
-- A "check-in" here is an attendance record where Rock says the person
-- attended (did_attend), on an occurrence that actually took place. It counts
-- every kind of attendance Rock records, not only weekend services. The
-- weekend_service and serving columns split out the two kinds that matter.
--
-- Giving is deliberately NOT here. It lives in door_holder_giving so access
-- to it can be restricted separately in Power BI.
--
-- Email and exact birth date are also left out; age is computed instead.

with memberships as (

    select
        m.person_key,
        m.added_at,
        (m.is_currently_active_member and g.is_currently_active)
                                                            as is_active_membership,
        g.is_door_holder_team,
        g.is_connect_group
    from {{ ref('fct_group_membership') }} m
    inner join {{ ref('dim_group') }} g
        on g.group_key = m.group_key

),

door_holder_memberships as (

    select
        person_key,
        logical_or(is_active_membership)                    as is_active_door_holder,
        countif(is_active_membership)                       as active_door_holder_team_count,
        min(date(added_at))                                 as first_door_holder_added_date
    from memberships
    where is_door_holder_team
    group by person_key

),

connect_group_memberships as (

    select
        person_key,
        countif(is_active_membership)                       as active_connect_group_count
    from memberships
    where is_connect_group
    group by person_key

),

door_holder_requests as (

    select
        person_key,
        count(*)                                            as door_holder_request_count,
        min(date(created_at))                               as first_door_holder_request_date,
        logical_or(is_connected)                            as has_connected_door_holder_request
    from {{ ref('fct_connection_request') }}
    where request_category = 'Door Holder'
      and person_key is not null
    group by person_key

),

-- Each occurrence with the kind of group it belongs to, so check-ins can be
-- split into weekend service, serving, and everything else.
occurrence_groups as (

    select
        o.occurrence_id,
        o.occurrence_date,
        o.sunday_date,
        o.did_occur,
        g.is_door_holder_team,
        gt.attendance_counts_as_weekend_service             as counts_as_weekend_service
    from {{ ref('stg_rock__attendance_occurrences') }} o
    left join {{ ref('dim_group') }} g
        on g.group_id = o.group_id
    left join {{ ref('stg_rock__group_types') }} gt
        on gt.group_type_id = g.group_type_id

),

aliases as (

    select person_alias_id, person_id
    from {{ ref('stg_rock__person_aliases') }}

),

-- Attendance that actually happened, resolved from Rock's alias id to a
-- person, and kept only for door holders to keep this small.
check_ins as (

    select
        dh.person_key,
        oc.occurrence_date,
        oc.sunday_date,
        oc.is_door_holder_team,
        oc.counts_as_weekend_service
    from {{ ref('stg_rock__attendance') }} a
    inner join aliases al
        on al.person_alias_id = a.person_alias_id
    inner join door_holder_memberships dh
        on dh.person_key = farm_fingerprint(cast(al.person_id as string))
    inner join occurrence_groups oc
        on oc.occurrence_id = a.occurrence_id
    where a.did_attend
      and oc.did_occur

),

check_in_history as (

    select
        person_key,
        count(*)                                            as check_ins_total,
        min(occurrence_date)                                as first_check_in_date,
        max(occurrence_date)                                as last_check_in_date,

        countif(occurrence_date >= date_sub(current_date(), interval 90 day))
                                                            as check_ins_last_90_days,
        countif(occurrence_date >= date_sub(current_date(), interval 12 month))
                                                            as check_ins_last_12_months,

        -- how many different weeks in the last year they checked in at all
        count(distinct if(
            occurrence_date >= date_sub(current_date(), interval 12 month),
            sunday_date,
            null
        ))                                                  as weeks_checked_in_last_12_months,

        countif(
            counts_as_weekend_service
            and occurrence_date >= date_sub(current_date(), interval 12 month)
        )                                                   as weekend_service_check_ins_last_12_months,

        countif(
            is_door_holder_team
            and occurrence_date >= date_sub(current_date(), interval 12 month)
        )                                                   as serving_check_ins_last_12_months

    from check_ins
    group by person_key

)

select
    dh.person_key,
    p.person_id,

    -- demographics
    p.full_name,
    p.gender,
    p.marital_status,
    p.campus_id,
    p.campus_name,
    p.is_active                                             as is_person_active,

    -- Whole years, from the exact birth date. Null when Rock has no complete
    -- birth date for the person.
    case
        when p.birth_date is not null then
            date_diff(current_date(), p.birth_date, year)
            - if(format_date('%m%d', current_date()) < format_date('%m%d', p.birth_date), 1, 0)
    end                                                     as age,

    -- serving
    coalesce(dh.is_active_door_holder, false)               as is_active_door_holder,
    dh.active_door_holder_team_count,
    dh.first_door_holder_added_date,
    date_diff(current_date(), dh.first_door_holder_added_date, day)
                                                            as days_since_first_joined,

    -- check-in history
    coalesce(ch.check_ins_total, 0)                         as check_ins_total,
    ch.first_check_in_date,
    ch.last_check_in_date,
    date_diff(current_date(), ch.last_check_in_date, day)   as days_since_last_check_in,
    coalesce(ch.check_ins_last_90_days, 0)                  as check_ins_last_90_days,
    coalesce(ch.check_ins_last_12_months, 0)                as check_ins_last_12_months,
    coalesce(ch.weeks_checked_in_last_12_months, 0)         as weeks_checked_in_last_12_months,
    coalesce(ch.weekend_service_check_ins_last_12_months, 0)
                                                            as weekend_service_check_ins_last_12_months,
    coalesce(ch.serving_check_ins_last_12_months, 0)        as serving_check_ins_last_12_months,

    -- other engagement: connect groups
    coalesce(cg.active_connect_group_count, 0) > 0          as is_in_connect_group,
    coalesce(cg.active_connect_group_count, 0)              as active_connect_group_count,

    -- how they came in: door holder join requests
    coalesce(rq.door_holder_request_count, 0)               as door_holder_request_count,
    rq.first_door_holder_request_date,
    coalesce(rq.has_connected_door_holder_request, false)   as has_connected_door_holder_request

from door_holder_memberships dh
inner join {{ ref('dim_person') }} p
    on p.person_key = dh.person_key
left join check_in_history ch
    on ch.person_key = dh.person_key
left join connect_group_memberships cg
    on cg.person_key = dh.person_key
left join door_holder_requests rq
    on rq.person_key = dh.person_key
