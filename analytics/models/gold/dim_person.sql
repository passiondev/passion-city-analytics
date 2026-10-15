-- One row per person record in Rock, current state only.
--
-- CONTAINS PERSONAL DATA: email and exact birth date. Access to the gold
-- dataset must stay limited to people trusted with it. Reports that do not
-- need these fields should select only the columns they use.
--
-- Facts (attendance, giving, connection requests) store a person_alias_id,
-- not a person_id. Each fact model resolves that when it is built, through
-- stg_rock__person_aliases, and stores person_key itself:
--     left join {{ ref('stg_rock__person_aliases') }} a
--         on a.person_alias_id = f.person_alias_id
--     ...
--     farm_fingerprint(cast(a.person_id as string)) as person_key
-- Anyone querying a fact then joins fact.person_key = dim_person.person_key.

with people as (

    select * from {{ ref('stg_rock__people') }}

),

defined_values as (

    select defined_value_id, value
    from {{ ref('stg_rock__defined_values') }}

),

campuses as (

    select campus_id, name as campus_name
    from {{ ref('stg_rock__campuses') }}

)

select
    -- surrogate key generated in the warehouse; person_id is Rock's own id
    farm_fingerprint(cast(p.person_id as string))           as person_key,
    p.person_id,
    p.person_guid,

    -- name
    p.display_name,
    p.first_name,
    p.last_name,
    p.full_name,

    -- demographics
    p.gender,
    p.birth_date,
    p.birth_year,
    marital.value                                           as marital_status,

    -- Rock's record type separates people from businesses and nameless
    -- check-in records. Keep them all: businesses can be donors, and dropping
    -- them would lose rows from giving facts.
    record_type.value                                       as record_type,
    record_status.value                                     as record_status,
    connection_status.value                                 as connection_status,

    -- contact
    p.email,
    p.is_email_active,
    p.email_preference,

    -- place
    p.primary_campus_id                                     as campus_id,
    campus.campus_name,
    p.primary_family_id,

    -- state
    p.is_active,
    p.is_deceased,

    p.created_at,
    p.updated_at

from people p
left join defined_values marital
    on marital.defined_value_id = p.marital_status_value_id
left join defined_values record_type
    on record_type.defined_value_id = p.record_type_value_id
left join defined_values record_status
    on record_status.defined_value_id = p.record_status_value_id
left join defined_values connection_status
    on connection_status.defined_value_id = p.connection_status_value_id
left join campuses campus
    on campus.campus_id = p.primary_campus_id
