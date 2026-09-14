"""
Load the Rock RMS `Person` table into BigQuery's `bronze` dataset.

Bronze principle: land the data as close to raw as possible. We add a small
amount of ingestion metadata (_loaded_at, _source_system) but do NOT rename
columns, cast types, or apply business logic here — that all happens in the
dbt staging model downstream.

Usage:
    python load_rock_person_to_bigquery.py --mode full        # full reload
    python load_rock_person_to_bigquery.py --mode incremental  # only changed rows

Requires:
    pip install pyodbc pandas google-cloud-bigquery db-dtypes

Environment variables expected (set these in your scheduler / secrets manager,
never hardcode credentials):
    ROCK_DB_SERVER      e.g. "rockdb.mychurch.org,1433"
    ROCK_DB_NAME        e.g. "Rock"
    ROCK_DB_USER
    ROCK_DB_PASSWORD
    GCP_PROJECT_ID      e.g. "my-warehouse-project"
    BQ_BRONZE_DATASET   defaults to "bronze"
"""

import argparse
import datetime
import os
import sys

import pandas as pd
import pyodbc
from google.cloud import bigquery

BQ_TABLE = "rock_people"
CHUNK_SIZE = 50_000  # rows per fetch batch, tune to your memory/network

# Columns pulled from Rock's Person table. This is the common core column
# set across recent Rock RMS versions — check against your instance's actual
# schema (SELECT * FROM Person, or your DB tooling) and adjust before running,
# since custom Rock installs sometimes add attribute columns via AttributeValue
# rather than directly on Person.
PERSON_COLUMNS = [
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
    "RecordSourceValueId"
]


def get_sql_server_connection() -> pyodbc.Connection:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['ROCK_DB_SERVER']};"
        f"DATABASE={os.environ['ROCK_DB_NAME']};"
        f"UID={os.environ['ROCK_DB_USER']};"
        f"PWD={os.environ['ROCK_DB_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


def build_query(mode: str) -> str:
    cols = ", ".join(f"[{c}]" for c in dict.fromkeys(PERSON_COLUMNS))  # de-dupe, preserve order
    base = f"SELECT {cols} FROM dbo.Person"
    if mode == "incremental":
        # Adjust the lookback window to match your load schedule + tolerance
        # for late-arriving edits. 26 hours covers a daily job with slack.
        base += " WHERE ModifiedDateTime >= DATEADD(HOUR, -26, GETUTCDATE())"
    return base


def extract(mode: str) -> pd.DataFrame:
    query = build_query(mode)
    with get_sql_server_connection() as conn:
        chunks = pd.read_sql(query, conn, chunksize=CHUNK_SIZE)
        df = pd.concat(chunks, ignore_index=True)

    df["_loaded_at"] = datetime.datetime.utcnow()
    df["_source_system"] = "rock_rms"
    return df


def load_to_bigquery(df: pd.DataFrame, mode: str) -> None:
    project_id = os.environ["GCP_PROJECT_ID"]
    dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
    table_ref = f"{project_id}.{dataset}.{BQ_TABLE}"

    client = bigquery.Client(project=project_id)

    if mode == "full":
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
    else:
        # Incremental: load into a staging table, then MERGE on Id so we
        # upsert rather than append duplicates.
        write_disposition = bigquery.WriteDisposition.WRITE_APPEND
        table_ref = f"{project_id}.{dataset}._stg_{BQ_TABLE}"

    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        autodetect=True,
    )
    job = client.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()
    print(f"Loaded {len(df):,} rows into {table_ref}")

    if mode == "incremental":
        merge_sql = f"""
        MERGE `{project_id}.{dataset}.{BQ_TABLE}` T
        USING `{table_ref}` S
        ON T.Id = S.Id
        WHEN MATCHED THEN UPDATE SET
          {", ".join(f"T.{c} = S.{c}" for c in dict.fromkeys(PERSON_COLUMNS) if c != "Id")},
          T._loaded_at = S._loaded_at
        WHEN NOT MATCHED THEN INSERT ROW
        """
        client.query(merge_sql).result()
        client.query(f"DROP TABLE `{table_ref}`").result()
        print("Merged incremental batch into bronze.rock_people")


def reconcile_deletes(project_id: str, dataset: str) -> None:
    """
    Polling by ModifiedDateTime never sees hard deletes on the Rock side
    (a row that's gone doesn't show up as a "changed" row to poll for).
    This pulls the full current set of Ids from Rock and removes any
    bronze row whose Id is no longer present. Run this less frequently
    than the main incremental job (e.g. nightly) since it requires a full
    scan of Person.Id on the source.
    """
    with get_sql_server_connection() as conn:
        current_ids = pd.read_sql("SELECT Id FROM dbo.Person", conn)

    client = bigquery.Client(project=project_id)
    ids_table = f"{project_id}.{dataset}._current_rock_person_ids"
    job = client.load_table_from_dataframe(
        current_ids,
        ids_table,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE"),
    )
    job.result()

    delete_sql = f"""
    DELETE FROM `{project_id}.{dataset}.{BQ_TABLE}` T
    WHERE T.Id NOT IN (SELECT Id FROM `{ids_table}`)
    """
    result = client.query(delete_sql).result()
    print(f"Reconciled deletes against {ids_table}; removed {result.num_dml_affected_rows or 0} rows")
    client.query(f"DROP TABLE `{ids_table}`").result()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument(
        "--reconcile-deletes",
        action="store_true",
        help="After loading, remove bronze rows whose Id no longer exists in Rock. "
             "Run this on a slower cadence (e.g. nightly) than the main incremental job.",
    )
    args = parser.parse_args()

    df = extract(args.mode)
    if df.empty:
        print("No rows extracted; exiting.")
    else:
        load_to_bigquery(df, args.mode)

    if args.reconcile_deletes:
        project_id = os.environ["GCP_PROJECT_ID"]
        dataset = os.environ.get("BQ_BRONZE_DATASET", "bronze")
        reconcile_deletes(project_id, dataset)


if __name__ == "__main__":
    main()
