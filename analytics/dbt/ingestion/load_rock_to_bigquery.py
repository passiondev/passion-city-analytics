"""
Load Rock RMS tables into BigQuery's `bronze` dataset.

Config-driven: add a new table by adding an entry to TABLE_CONFIGS below —
no new script, no code duplication. Each table is loaded independently via
the --table flag, so scheduling can add tables one at a time.

Bronze principle: land the data as close to raw as possible. We add a small
amount of ingestion metadata (_loaded_at, _source_system) but do NOT rename
columns, cast types, or apply business logic here — that all happens in dbt
staging models downstream.

Usage:
    python load_rock_to_bigquery.py --table person --mode full
    python load_rock_to_bigquery.py --table person --mode incremental
    python load_rock_to_bigquery.py --table person --mode incremental --reconcile-deletes
    python load_rock_to_bigquery.py --list-tables

Requires:
    pip install pyodbc pandas google-cloud-bigquery db-dtypes

Environment variables expected (set these in your scheduler / secrets manager,
never hardcode credentials):
    ROCK_DB_SERVER      e.g. "10.1.2.3,1433"
    ROCK_DB_NAME        e.g. "Rock"
    ROCK_DB_USER
    ROCK_DB_PASSWORD
    GCP_PROJECT_ID      e.g. "bigquery-test-469018"
    BQ_BRONZE_DATASET   defaults to "bronze"
"""

import argparse
import datetime
import os

import pandas as pd
import pyodbc
from google.cloud import bigquery

CHUNK_SIZE = 50_000  # rows per fetch batch, tune to your memory/network

# ---------------------------------------------------------------------------
# TABLE CONFIGS — add a new table by adding an entry here.
#
#   source_table       fully-qualified source table, e.g. "dbo.Person"
#   columns             list of columns to pull (order preserved, de-duped)
#   bq_table            destination table name in bronze (per naming conventions:
#                       <source>_<entity>, plural — e.g. "rock_people")
#   primary_key         column used to upsert/merge and to reconcile deletes
#   modified_column     column used for incremental "what changed" filtering
# ---------------------------------------------------------------------------
TABLE_CONFIGS = {
    "person": {
        "source_table": "dbo.Person",
        "primary_key": "Id",
        "modified_column": "ModifiedDateTime",
        "bq_table": "rock_people",
        "columns": [
            "Id",
            "IsSystem",
            "RecordTypeValueId",
            "RecordStatusValueId",
            "RecordStatusReasonValueId",
            "ConnectionStatusValueId",
            "IsDeceased",
            "TitleValueId",
            "FirstName",
            "NickName",
            "MiddleName",
            "LastName",
            "SuffixValueId",
            "PhotoId",
            "BirthDay",
            "BirthMonth",
            "BirthYear",
            "Gender",
            "MaritalStatusValueId",
            "AnniversaryDate",
            "GivingGroupId",
            "Email",
            "IsEmailActive",
            "EmailNote",
            "SystemNote",
            "ViewedCount",
            "Guid",
            "CreatedDateTime",
            "ModifiedDateTime",
            "CreatedByPersonAliasId",
            "ModifiedByPersonAliasId",
            "EmailPreference",
            "InactiveReasonNote",
            "ForeignKey",
            "ReviewReasonValueId",
            "ReviewReasonNote",
            "GraduationYear",
            "ForeignGuid",
            "ForeignId",
            "RecordStatusLastModifiedDateTime",
            "CommunicationPreference",
            "TopSignalColor",
            "TopSignalIconCssClass",
            "TopSignalId",
            "AgeClassification",
            "PrimaryFamilyId",
            "DaysUntilAnniversary",
            "IsLockedAsChild",
            "DeceasedDate",
            "GivingLeaderId",
            "BirthDate",
            "ContributionFinancialAccountId",
            "PrimaryCampusId",
            "GivingId",
            "PreferredLanguageValueId",
            "AccountProtectionProfile",
            "DaysUntilBirthday",
            "ReminderCount",
            "RaceValueId",
            "EthnicityValueId",
            "BirthDateKey",
            "AgeBracket",
            "Age",
            "FirstNamePronunciationOverride",
            "NickNamePronunciationOverride",
            "LastNamePronunciationOverride",
            "PronunciationNote",
            "PrimaryAliasId",
            "PrimaryAliasGuid",
            "IsChatProfilePublic",
            "IsChatOpenDirectMessageAllowed",
            "RecordSourceValueId",
        ],
    },

    # Example of what adding a second table looks like — fill in real columns
    # before using. Rock's Group table is a common next candidate (families,
    # small groups, serving teams all live here).
    #
    # "group": {
    #     "source_table": "dbo.Group",
    #     "primary_key": "Id",
    #     "modified_column": "ModifiedDateTime",
    #     "bq_table": "rock_groups",
    #     "columns": [
    #         "Id",
    #         "Guid",
    #         "GroupTypeId",
    #         "Name",
    #         "IsActive",
    #         "ParentGroupId",
    #         "CampusId",
    #         "CreatedDateTime",
    #         "ModifiedDateTime",
    #     ],
    # },
}


from google.cloud.sql.connector import Connector

def get_sql_server_connection():
    connector = Connector()
    conn = connector.connect(
        os.environ["CLOUDSQL_INSTANCE_CONNECTION_NAME"],  # "project:region:instance"
        "pytds",
        user=os.environ["ROCK_DB_USER"],
        password=os.environ["ROCK_DB_PASSWORD"],
        db=os.environ["ROCK_DB_NAME"],
    )
    return conn


def build_query(config: dict, mode: str) -> str:
    cols = ", ".join(f"[{c}]" for c in dict.fromkeys(config["columns"]))  # de-dupe, preserve order
    base = f"SELECT {cols} FROM {config['source_table']}"
    if mode == "incremental":
        # Adjust the lookback window to match your load schedule + tolerance
        # for late-arriving edits. 26 hours covers a daily job with slack.
        base += f" WHERE [{config['modified_column']}] >= DATEADD(HOUR, -26, GETUTCDATE())"
    return base


def extract(config: dict, mode: str) -> pd.DataFrame:
    query = build_query(config, mode)
    with get_sql_server_connection() as conn:
        chunks = pd.read_sql(query, conn, chunksize=CHUNK_SIZE)
        df = pd.concat(chunks, ignore_index=True)

    df["_loaded_at"] = datetime.datetime.utcnow()
    df["_source_system"] = "rock_rms"
    return df


def load_to_bigquery(df: pd.DataFrame, config: dict, mode: str) -> None:
    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
    bq_table = config["bq_table"]
    pk = config["primary_key"]
    table_ref = f"{project_id}.{dataset}.{bq_table}"

    client = bigquery.Client(project=project_id)

    if mode == "full":
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        job_config = bigquery.LoadJobConfig(
            write_disposition=write_disposition,
            autodetect=True,
        )
    else:
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        table_ref = f"{project_id}.{dataset}._stg_{bq_table}"

        # Reuse the target table's existing schema rather than autodetect.
        # autodetect infers types independently per load based on whatever
        # sample of rows is present — a batch where a column happens to be
        # all-null can get inferred as a different type (e.g. STRING
        # instead of FLOAT64) than the original full load saw, causing the
        # MERGE below to fail on a type mismatch. Locking to the target's
        # committed schema keeps every incremental load type-consistent.
        target_table = client.get_table(f"{project_id}.{dataset}.{bq_table}")
        staging_schema = [field for field in target_table.schema]
        job_config = bigquery.LoadJobConfig(
            write_disposition=write_disposition,
            schema=staging_schema,
        )
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
    print(f"Loaded {len(df):,} rows into {table_ref}")

    if mode == "incremental":
        update_cols = [c for c in dict.fromkeys(config["columns"]) if c != pk]
        merge_sql = f"""
        MERGE `{project_id}.{dataset}.{bq_table}` T
        USING `{table_ref}` S
        ON T.{pk} = S.{pk}
        WHEN MATCHED THEN UPDATE SET
          {", ".join(f"T.{c} = S.{c}" for c in update_cols)},
          T._loaded_at = S._loaded_at
        WHEN NOT MATCHED THEN INSERT ROW
        """
        client.query(merge_sql).result()
        client.query(f"DROP TABLE `{table_ref}`").result()
        print(f"Merged incremental batch into {dataset}.{bq_table}")


def reconcile_deletes(config: dict, project_id: str, dataset: str) -> None:
    """
    Polling by modified_column never sees hard deletes on the Rock side (a
    row that's gone doesn't show up as a "changed" row to poll for). This
    pulls the full current set of primary keys from Rock and removes any
    bronze row no longer present. Run this less frequently than the main
    incremental job (e.g. nightly) since it requires a full scan of the
    source table's primary key column.
    """
    pk = config["primary_key"]
    bq_table = config["bq_table"]

    with get_sql_server_connection() as conn:
        current_ids = pd.read_sql(f"SELECT {pk} FROM {config['source_table']}", conn)

    client = bigquery.Client(project=project_id)
    ids_table = f"{project_id}.{dataset}._current_{bq_table}_ids"
    job = client.load_table_from_dataframe(
        current_ids,
        ids_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()

    delete_sql = f"""
    DELETE FROM `{project_id}.{dataset}.{bq_table}` T
    WHERE T.{pk} NOT IN (SELECT {pk} FROM `{ids_table}`)
    """
    result = client.query(delete_sql).result()
    print(f"Reconciled deletes against {ids_table}; removed {result.num_dml_affected_rows or 0} rows")
    client.query(f"DROP TABLE `{ids_table}`").result()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", choices=sorted(TABLE_CONFIGS.keys()), help="Which configured table to load")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument(
        "--reconcile-deletes",
        action="store_true",
        help="After loading, remove bronze rows whose primary key no longer exists in Rock. "
             "Run this on a slower cadence (e.g. nightly) than the main incremental job.",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="Print configured table keys and exit.",
    )
    args = parser.parse_args()

    if args.list_tables:
        for key, cfg in TABLE_CONFIGS.items():
            print(f"{key:12s} -> {cfg['source_table']:20s} -> bronze.{cfg['bq_table']}")
        return

    if not args.table:
        parser.error("--table is required (or use --list-tables to see options)")

    config = TABLE_CONFIGS[args.table]

    df = extract(config, args.mode)
    if df.empty:
        print("No rows extracted; exiting.")
    else:
        load_to_bigquery(df, config, args.mode)

    if args.reconcile_deletes:
        project_id = os.environ["GCP_PROJECT_ID"]
        dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
        reconcile_deletes(config, project_id, dataset)


if __name__ == "__main__":
    main()
