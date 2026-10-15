-- One row per calendar day. Every fact joins to it on a YYYYMMDD integer
-- date_key, as the naming conventions describe.

with days as (

    select date_day
    from unnest(generate_date_array(date '2000-01-01', date '2040-12-31')) as date_day

)

select
    cast(format_date('%Y%m%d', date_day) as int64)          as date_key,
    date_day,
    extract(year from date_day)                             as calendar_year,
    extract(quarter from date_day)                          as calendar_quarter,
    extract(month from date_day)                            as month_number,
    format_date('%B', date_day)                             as month_name,
    date_trunc(date_day, month)                             as month_start_date,

    -- 1 = Sunday through 7 = Saturday
    extract(dayofweek from date_day)                        as day_of_week_number,
    format_date('%A', date_day)                             as day_of_week_name,
    extract(dayofweek from date_day) in (1, 7)              as is_weekend,

    -- Rock's weekly rollup date: the Sunday that ends the Monday-to-Sunday
    -- week containing this day. Matches Rock's SundayDate columns.
    date_add(date_trunc(date_day, week(monday)), interval 6 day)
                                                            as sunday_date

from days
