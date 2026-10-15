-- One row per person: their current snapshot only. Always fresh since this
-- is a view — re-reads stg_rock__person_historical (itself a view over
-- bronze) on every query, so there's no incremental-loading staleness
-- concern here despite bronze only refreshing via full reload.

select *
from {{ ref('stg_rock__person_historical') }}
where is_current_row
