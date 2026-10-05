# Rock RMS → BigQuery Bronze → dbt Silver

## What's in this folder

```
DEPLOYMENT.md                          # scheduling: Cloud Run Job + Cloud Scheduler, multi-table
scripts/
  load_rock_to_bigquery.py            # config-driven loader — add a table via TABLE_CONFIGS, no new script
models/staging/rock/
  _rock__sources.yml                   # dbt source def + column docs for bronze.rock_people
  stg_rock__people.sql                 # staging model: renames, decodes codes, business logic
  _rock__models.yml                    # docs + tests for stg_rock__people
```

## Adding a new table

1. Add an entry to `TABLE_CONFIGS` in `load_rock_to_bigquery.py` (source
   table, columns, primary key, destination bronze table name).
2. Run a full load for it: `python load_rock_to_bigquery.py --table <key> --mode full`
3. Add a matching dbt source entry + staging model under
   `models/staging/rock/`, following the `stg_rock__people` pattern.
4. Once scheduling is live, add one Cloud Scheduler trigger for it — see
   `DEPLOYMENT.md` section 5.

## Setup steps (for the `person` table specifically)

### 1. Load bronze — scheduled polling (Web Edition has no CDC available)

Install deps and set credentials as environment variables (use Secret
Manager in production — never commit these):

```bash
pip install pyodbc pandas google-cloud-bigquery db-dtypes

export ROCK_DB_SERVER="10.x.x.x,1433"
export ROCK_DB_NAME="Rock"
export ROCK_DB_USER="..."
export ROCK_DB_PASSWORD="..."
export GCP_PROJECT_ID="bigquery-test-469018"
export BQ_BRONZE_DATASET="bronze"

python scripts/load_rock_to_bigquery.py --table person --mode full
```

This creates/replaces `bronze.rock_people`. For ongoing loads, run with
`--mode incremental` on a schedule — it upserts on the table's primary key
instead of truncating. Add `--reconcile-deletes` on a slower cadence (e.g.
nightly) to catch hard deletes, which timestamp-based polling otherwise
misses entirely. See **`DEPLOYMENT.md`** for the full Cloud Run Job +
Cloud Scheduler setup, including how additional tables get scheduled
without new infrastructure.

### 2. Drop the dbt files into your project

Copy `models/staging/rock/` into your dbt project's `models/staging/`
folder (in this repo: `analytics/models/staging/`).

### 3. Confirm dataset location matches

`bronze`/`silver`/`gold` live in `us-east1` in this project — make sure
your dbt profile's `location:` is set to `us-east1`, not the `US`
multi-region default, or sources/models will fail with a "not found in
location" error.

### 4. Set the "active" DefinedValue id (one-time)

The staging model's `is_active` logic depends on Rock's `DefinedValue.Id`
for Record Status = "Active", which varies by instance:

```sql
-- run against Rock's SQL Server
SELECT dv.Id, dv.Value
FROM DefinedValue dv
JOIN DefinedType dt ON dt.Id = dv.DefinedTypeId
WHERE dt.Name = 'Record Status'
```

Then set it in `dbt_project.yml`:

```yaml
vars:
  rock_record_status_active_id: <the id you found>
```

### 5. Confirm dataset routing (silver) and the schema macro

`dbt_project.yml` needs:

```yaml
models:
  analytics:                # match the `name:` field at the top of dbt_project.yml
    staging:
      +schema: silver
      +materialized: view
```

and `macros/generate_schema_name.sql`:

```sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

Without this macro, dbt defaults to `<target_schema>_silver` (e.g.
`dbt_yourname_silver`) instead of just `silver`.

### 6. Run it

```bash
dbt run --select stg_rock__people
dbt test --select stg_rock__people
dbt docs generate && dbt docs serve
```

## Notes / things to double check

- `is_active`, `email_preference`, and `gender` decoding are the "business
  logic" pieces — validated against real people in Rock, not just assumed
  correct. Worth re-checking if Rock's DefinedValue mappings ever change.
- Bronze intentionally stays unmodified (raw column names, raw codes,
  including Rock's own encodings like `Gender=0` meaning "Unknown," not
  missing data). All renaming/decoding lives in the staging model.
- Staging models are 1:1 with bronze in row count by design — they clean
  and conform, they don't filter. Filtering to "active people only" or
  similar belongs in a downstream mart that references
  `stg_rock__people`, not in staging itself.
- This is timestamp-based polling, not CDC (Web Edition doesn't support
  SQL Server's Change Data Capture feature — that needs Standard/
  Enterprise). The `--reconcile-deletes` pass covers the main gap (hard
  deletes) but there's inherent latency between polls that CDC wouldn't
  have. If the Cloud SQL edition is ever upgraded, Datastream becomes an
  option and could replace this script.
- If Rock has attribute-based custom fields (stored in `AttributeValue`
  rather than directly on `Person`), those aren't included here — they'd
  need a separate pivot/unpivot step.
