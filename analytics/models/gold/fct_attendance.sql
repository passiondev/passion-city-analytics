-- One row per person per attendance occurrence (a check-in or attendance record).
--
-- Rock stores attendance in two tables: Attendance (who) and
-- AttendanceOccurrence (when / where / which group). This model joins them so
-- each row carries the date, group, location and schedule of the occurrence.
-- There is no separate occurrence fact: Sunday service totals are not tracked
-- per person, so everything needed lives on this row.
--
-- person_alias_id is resolved to person_id through stg_rock__person_aliases so
-- the fact joins to dim_person on person_key.

with attendance as (

    select * from {{ ref('stg_rock__attendance') }}

),

occurrences as (

    select * from {{ ref('stg_rock__attendance_occurrences') }}

),

aliases as (

    select person_alias_id, person_id from {{ ref('stg_rock__person_aliases') }}

)

select
    farm_fingerprint(cast(a.attendance_id as string))           as attendance_key,
    a.attendance_id,
    farm_fingerprint(cast(al.person_id as string))              as person_key,
    a.occurrence_id,
    farm_fingerprint(cast(o.group_id as string))                as group_key,
    o.location_id,
    o.schedule_id,
    a.campus_id,
    cast(format_date('%Y%m%d', o.occurrence_date) as int64)     as date_key,
    o.occurrence_date,
    o.sunday_date,
    a.started_at,
    a.ended_at,
    a.did_attend,
    o.did_occur,
    coalesce(a.did_attend and o.did_occur, false)               as is_check_in,
    a.rsvp,
    a.is_first_time,
    a.is_scheduled_to_attend,
    a.updated_at

from attendance a
left join aliases al
    on al.person_alias_id = a.person_alias_id
left join occurrences o
    on o.occurrence_id = a.occurrence_id
