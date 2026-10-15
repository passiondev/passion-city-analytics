-- One row per door holder, with Rock's giving journey fields for that person.
-- Every journey stage is passed through as Rock reports it; nothing is
-- sorted into giver or non-giver here.
--
-- CONTAINS INDIVIDUAL FINANCIAL DATA. It is kept in its own table, separate
-- from door_holder_engagement, so Power BI can restrict who sees it.
--
-- The values come from Rock's analytics history table, which is reloaded on
-- its own schedule. giving_data_loaded_at shows when that table was last
-- loaded, so anyone reading a stage can see how current it is.

with door_holders as (

    select person_key, person_id
    from {{ ref('door_holder_engagement') }}

),

journey as (

    select
        person_id,
        current_journey_giving_stage,
        previous_journey_giving_stage,
        journey_giving_stage_change_date,
        giving_bin,
        giving_percentile,
        next_expected_gift_date,
        _bronze_loaded_at
    from {{ ref('stg_rock__person_current') }}

)

select
    d.person_key,

    j.current_journey_giving_stage,
    j.previous_journey_giving_stage,
    j.journey_giving_stage_change_date,
    j.giving_bin,
    j.giving_percentile,
    j.next_expected_gift_date,

    j._bronze_loaded_at                                     as giving_data_loaded_at

from door_holders d
left join journey j
    on j.person_id = d.person_id
