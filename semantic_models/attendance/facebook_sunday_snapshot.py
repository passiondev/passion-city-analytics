#!/usr/bin/env python3


import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from google.cloud import bigquery


# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

PROJECT = "bigquery-test-469018"
DATASET = "youtube_passion_city_church"
TABLE = f"{PROJECT}.{DATASET}.facebook_sunday_snapshot"

PAGE_ID = "192924437428798"

GRAPH_VERSION = "v25.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

METRIC = "total_video_60s_excludes_shorter_views"

EASTERN = ZoneInfo("America/New_York")

ACCESS_TOKEN = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")


# ----------------------------------------------------------------------
# META API ERROR
# ----------------------------------------------------------------------

class MetaAPIError(RuntimeError):
    def __init__(
        self,
        message,
        code=None,
        subcode=None,
        error_type=None,
    ):
        self.code = code
        self.subcode = subcode
        self.error_type = error_type

        super().__init__(
            f"Meta API error "
            f"code={code} "
            f"subcode={subcode} "
            f"type={error_type}: "
            f"{message}"
        )


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------

def parse_meta_datetime(value):
    if not value:
        return None

    value = value.replace("Z", "+00:00")

    # Meta sometimes returns +0000 instead of +00:00.
    if (
        len(value) >= 5
        and value[-5] in ("+", "-")
        and value[-3] != ":"
    ):
        value = value[:-2] + ":" + value[-2:]

    return datetime.fromisoformat(value)


def meta_get(path_or_url, params=None):
    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        url = f"{GRAPH_BASE}/{path_or_url.lstrip('/')}"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=60,
    )

    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(
            f"Meta returned HTTP {response.status_code} "
            "with a non-JSON response."
        )

    if "error" in payload:
        error = payload["error"]

        raise MetaAPIError(
            message=error.get(
                "message",
                "Unknown Meta API error",
            ),
            code=error.get("code"),
            subcode=error.get("error_subcode"),
            error_type=error.get("type"),
        )

    if not response.ok:
        raise RuntimeError(
            f"Meta returned HTTP {response.status_code}"
        )

    return payload


# ----------------------------------------------------------------------
# LIVE VIDEO DISCOVERY
# ----------------------------------------------------------------------

def get_live_videos():
    live_videos = []
    seen_ids = set()

    url = f"{GRAPH_BASE}/{PAGE_ID}/live_videos"

    params = {
        "fields": (
            "id,"
            "title,"
            "status,"
            "creation_time,"
            "broadcast_start_time,"
            "planned_start_time,"
            "video{id}"
        ),
        "limit": 25,
    }

    page_number = 1

    while url:
        print(f"Reading Live Video page {page_number}...")

        payload = meta_get(
            url,
            params=params,
        )

        videos = payload.get("data", [])

        for live in videos:
            live_id = live.get("id")

            if live_id and live_id not in seen_ids:
                seen_ids.add(live_id)
                live_videos.append(live)

        print(
            f"  Found {len(videos)} on this page "
            f"({len(live_videos)} total so far)"
        )

        url = (
            payload
            .get("paging", {})
            .get("next")
        )

        # Meta's next URL already includes paging information.
        params = None
        page_number += 1

    return live_videos


# ----------------------------------------------------------------------
# FACEBOOK 1-MINUTE VIEW METRIC
# ----------------------------------------------------------------------

def get_one_minute_views(video_id):
    payload = meta_get(
        f"{video_id}/video_insights",
        params={
            "metric": METRIC
        },
    )

    for metric in payload.get("data", []):
        if metric.get("name") != METRIC:
            continue

        values = metric.get("values", [])

        if not values:
            return None

        value = values[0].get("value")

        if value is None:
            return None

        return int(value)

    return None


# ----------------------------------------------------------------------
# BIGQUERY: WHAT DO WE ALREADY HAVE?
# ----------------------------------------------------------------------

def get_existing_keys(bq, target_dates):
    """
    Return existing (sunday_date, gathering) combinations for the
    two-Sunday window.
    """

    sql = f"""
    SELECT
        sunday_date,
        gathering
    FROM `{TABLE}`
    WHERE sunday_date IN UNNEST(@target_dates)
    """

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "target_dates",
                "DATE",
                sorted(target_dates),
            )
        ]
    )

    results = bq.query(
        sql,
        job_config=config,
    ).result()

    existing = set()

    for row in results:
        existing.add(
            (
                row["sunday_date"],
                row["gathering"],
            )
        )

    return existing


# ----------------------------------------------------------------------
# DISCOVERY FOR TWO SUNDAYS
# ----------------------------------------------------------------------

def discover_rows(target_dates):
    print("Getting Facebook Live videos...")

    live_videos = get_live_videos()

    print(
        f"\nScanned {len(live_videos)} "
        "Facebook LiveVideo object(s)."
    )

    rows = []

    for live in live_videos:
        live_id = live.get("id")

        title = live.get("title") or ""

        broadcast_start = parse_meta_datetime(
            live.get("broadcast_start_time")
        )

        print(
            "  FOUND:",
            live_id,
            "|",
            title,
            "|",
            live.get("broadcast_start_time"),
        )

        if not title.startswith("Sunday Gathering //"):
            continue

        if not broadcast_start:
            continue

        local_start = broadcast_start.astimezone(EASTERN)

        sunday_date = local_start.date()

        # Only care about the requested two Sundays.
        if sunday_date not in target_dates:
            continue

        video = live.get("video") or {}
        video_id = video.get("id")

        if not video_id:
            print(
                "    SKIPPED - "
                "No underlying Video ID."
            )
            continue

        gathering = title.split("//", 1)[1].strip()

        try:
            views = get_one_minute_views(video_id)

        except MetaAPIError as error:
            if (
                error.code == 100
                and error.subcode == 33
            ):
                print(
                    "    SKIPPED - "
                    "Video object is no longer "
                    "accessible."
                )
                continue

            raise

        if views is None:
            print(
                "    SKIPPED - "
                "No 1-minute view value."
            )
            continue

        planned_start = parse_meta_datetime(
            live.get("planned_start_time")
        )

        creation_time = parse_meta_datetime(
            live.get("creation_time")
        )

        rows.append({
            "video_id": video_id,
            "live_video_id": live_id,
            "title": title,
            "gathering": gathering,
            "sunday_date": sunday_date.isoformat(),
            "one_minute_views": views,
            "broadcast_start_time": broadcast_start.isoformat(),
            "planned_start_time": (
                planned_start.isoformat()
                if planned_start
                else None
            ),
            "creation_time": (
                creation_time.isoformat()
                if creation_time
                else None
            ),
            "status": live.get("status"),
        })

        print(
            f"    MATCH: {sunday_date} "
            f"{gathering} = {views}"
        )

    return rows


# ----------------------------------------------------------------------
# BIGQUERY INSERT-ONLY MERGE
# ----------------------------------------------------------------------

UNPACK_SQL = """
SELECT
    JSON_VALUE(r, '$.video_id') AS video_id,
    JSON_VALUE(r, '$.live_video_id') AS live_video_id,
    JSON_VALUE(r, '$.title') AS title,
    JSON_VALUE(r, '$.gathering') AS gathering,

    SAFE_CAST(
        JSON_VALUE(r, '$.sunday_date')
        AS DATE
    ) AS sunday_date,

    SAFE_CAST(
        JSON_VALUE(r, '$.one_minute_views')
        AS INT64
    ) AS one_minute_views,

    SAFE_CAST(
        JSON_VALUE(r, '$.broadcast_start_time')
        AS TIMESTAMP
    ) AS broadcast_start_time,

    SAFE_CAST(
        JSON_VALUE(r, '$.planned_start_time')
        AS TIMESTAMP
    ) AS planned_start_time,

    SAFE_CAST(
        JSON_VALUE(r, '$.creation_time')
        AS TIMESTAMP
    ) AS creation_time,

    JSON_VALUE(r, '$.status') AS status

FROM UNNEST(
    JSON_EXTRACT_ARRAY(@rows_json)
) AS r
"""


def insert_missing_rows(bq, rows):
    if not rows:
        return

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "rows_json",
                "STRING",
                json.dumps(rows),
            )
        ]
    )

    sql = f"""
    MERGE `{TABLE}` t

    USING ({UNPACK_SQL}) s

    ON
        t.sunday_date = s.sunday_date
        AND t.gathering = s.gathering

    WHEN NOT MATCHED THEN
      INSERT (
        video_id,
        live_video_id,
        title,
        gathering,
        sunday_date,
        one_minute_views,
        broadcast_start_time,
        planned_start_time,
        creation_time,
        status,
        snapshot_taken_at
      )

      VALUES (
        s.video_id,
        s.live_video_id,
        s.title,
        s.gathering,
        s.sunday_date,
        s.one_minute_views,
        s.broadcast_start_time,
        s.planned_start_time,
        s.creation_time,
        s.status,
        CURRENT_TIMESTAMP()
      )
    """

    bq.query(
        sql,
        job_config=config,
    ).result()


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    if not ACCESS_TOKEN:
        print(
            "ERROR: FACEBOOK_PAGE_ACCESS_TOKEN "
            "environment variable is missing."
        )
        return 1

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        help=(
            "Most recent Sunday YYYY-MM-DD. "
            "That Sunday and the prior Sunday are scanned."
        ),
    )

    args = parser.parse_args()

    if args.date:
        latest_sunday = datetime.strptime(
            args.date,
            "%Y-%m-%d",
        ).date()

    else:
        today = datetime.now(EASTERN).date()

        latest_sunday = today - timedelta(
            days=(today.weekday() + 1) % 7
        )

    previous_sunday = (
        latest_sunday
        - timedelta(days=7)
    )

    target_dates = {
        latest_sunday,
        previous_sunday,
    }

    print("Facebook Sunday Snapshot")
    print()
    print("Scanning Sundays:")
    print(f"  {previous_sunday}")
    print(f"  {latest_sunday}")
    print()

    bq = bigquery.Client(project=PROJECT)

    existing_keys = get_existing_keys(
        bq,
        target_dates,
    )

    print("Existing BigQuery records:")

    if existing_keys:
        for sunday_date, gathering in sorted(existing_keys):
            print(
                f"  {sunday_date} | "
                f"{gathering}"
            )
    else:
        print("  None")

    print()

    discovered_rows = discover_rows(
        target_dates
    )

    missing_rows = []

    for row in discovered_rows:
        sunday_date = datetime.strptime(
            row["sunday_date"],
            "%Y-%m-%d",
        ).date()

        key = (
            sunday_date,
            row["gathering"],
        )

        if key in existing_keys:
            print(
                "SKIP EXISTING:",
                row["sunday_date"],
                "|",
                row["gathering"],
            )
            continue

        missing_rows.append(row)

    print()

    if not missing_rows:
        print(
            "No missing Sunday Gathering "
            "records were available from Meta."
        )

        print(
            "BigQuery was not changed."
        )

        print("\nDone.")

        return 0

    print("NEW RECORDS:")

    for row in missing_rows:
        print(
            f"  {row['sunday_date']} | "
            f"{row['gathering']} | "
            f"{row['one_minute_views']} "
            "1-minute views"
        )

    insert_missing_rows(
        bq,
        missing_rows,
    )

    print(
        f"\nInserted {len(missing_rows)} "
        "missing record(s) into BigQuery."
    )

    print("\nDone.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
