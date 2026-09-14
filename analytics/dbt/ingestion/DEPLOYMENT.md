# Scheduling Rock ingestion (multi-table)

The loader script (`load_rock_to_bigquery.py`) is config-driven — one Cloud
Run Job image serves every table. Adding a table later means: add a config
entry, redeploy the image, add one new Cloud Scheduler trigger. No new
infra.

## 1. Containerize the script

```dockerfile
FROM python:3.12-slim

# ODBC driver for SQL Server
RUN apt-get update && apt-get install -y curl gnupg unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY load_rock_to_bigquery.py .
RUN pip install pyodbc pandas google-cloud-bigquery db-dtypes

ENTRYPOINT ["python", "load_rock_to_bigquery.py"]
```

Build and push:

```bash
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/rock-loader
```

## 2. Create the Cloud Run Job

Set a default `--table` and `--mode` as the job's baseline args — these get
overridden per-invocation in step 4, so what you put here mostly just
matters for manual test runs.

```bash
gcloud run jobs create rock-loader \
  --image gcr.io/$GCP_PROJECT_ID/rock-loader \
  --region us-east1 \
  --set-env-vars GCP_PROJECT_ID=$GCP_PROJECT_ID,BQ_BRONZE_DATASET=bronze \
  --set-secrets ROCK_DB_SERVER=rock-db-server:latest,ROCK_DB_NAME=rock-db-name:latest,ROCK_DB_USER=rock-db-user:latest,ROCK_DB_PASSWORD=rock-db-password:latest \
  --args="--table=person,--mode=incremental"
```

Store connection details in Secret Manager (`gcloud secrets create ...`)
rather than plain env vars. If Cloud SQL isn't reachable over the network
Cloud Run Jobs use by default, add a VPC connector so the job can reach the
private IP (`--network`/`--vpc-connector` flags, or `--vpc-connector` alone
if one already exists).

## 3. Test it manually before scheduling anything

```bash
gcloud run jobs execute rock-loader --region us-east1 \
  --args="--table=person,--mode=full"
```

Check the BigQuery table populated correctly before moving to step 4.

## 4. Schedule per table/mode via container overrides

Cloud Scheduler triggers the Cloud Run Jobs API directly, passing a JSON
body that **overrides** the job's args for that specific invocation. This
is what lets one job definition serve multiple tables/modes on different
schedules — no need for a separate Cloud Run Job per table.

**Person — hourly incremental:**

```bash
gcloud scheduler jobs create http rock-person-incremental \
  --schedule="0 * * * *" \
  --uri="https://us-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/rock-loader:run" \
  --http-method=POST \
  --oauth-service-account-email=YOUR_SCHEDULER_SA@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --headers="Content-Type=application/json" \
  --message-body='{"overrides":{"containerOverrides":[{"args":["--table=person","--mode=incremental"]}]}}'
```

**Person — nightly delete reconciliation:**

```bash
gcloud scheduler jobs create http rock-person-reconcile \
  --schedule="0 3 * * *" \
  --uri="https://us-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/rock-loader:run" \
  --http-method=POST \
  --oauth-service-account-email=YOUR_SCHEDULER_SA@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --headers="Content-Type=application/json" \
  --message-body='{"overrides":{"containerOverrides":[{"args":["--table=person","--mode=incremental","--reconcile-deletes"]}]}}'
```

## 5. Adding a second table later — the whole process

Say you add a `group` config to `TABLE_CONFIGS` in the script:

```bash
# 1. rebuild and push the image (same command as step 1)
gcloud builds submit --tag gcr.io/$GCP_PROJECT_ID/rock-loader

# 2. point the existing Cloud Run Job at the new image (same job, new code)
gcloud run jobs update rock-loader --image gcr.io/$GCP_PROJECT_ID/rock-loader --region us-east1

# 3. one-time full load for the new table
gcloud run jobs execute rock-loader --region us-east1 --args="--table=group,--mode=full"

# 4. add its own scheduled trigger, same pattern as step 4 above
gcloud scheduler jobs create http rock-group-incremental \
  --schedule="0 * * * *" \
  --uri="https://us-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$GCP_PROJECT_ID/jobs/rock-loader:run" \
  --http-method=POST \
  --oauth-service-account-email=YOUR_SCHEDULER_SA@$GCP_PROJECT_ID.iam.gserviceaccount.com \
  --headers="Content-Type=application/json" \
  --message-body='{"overrides":{"containerOverrides":[{"args":["--table=group","--mode=incremental"]}]}}'
```

No new Dockerfile, no new Cloud Run Job resource, no VPC/networking
rework — just a config entry, a redeploy, and one new scheduler trigger.
On the dbt side, a new table means a new `source` entry + staging model,
same pattern as `stg_rock__people`.

## Why the delete-reconciliation step matters

Polling by a "modified since" timestamp only catches rows that changed — a
row deleted from Rock doesn't emit a "changed" event for polling to find.
Without reconciliation, deleted records would stay in bronze forever. The
nightly pass compares the full set of current primary keys in Rock against
what's in bronze and removes anything no longer present. This is one of
the tradeoffs of polling vs. CDC (CDC via Datastream would handle deletes
automatically, but isn't available without upgrading off Web Edition).
