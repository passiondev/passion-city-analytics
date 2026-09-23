#!/usr/bin/env python3
"""
facebook_sunday_snapshot.py

Pull Facebook Sunday Gathering livestreams, retrieve lifetime
1-minute views, and MERGE them into BigQuery.

Usage:
    python3 facebook_sunday_snapshot.py
    python3 facebook_sunday_snapshot.py --date 2026-09-20
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from google.cloud import bigquery


# ----------------------------------------------------------------------
# --CONFIG
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
# --HELPERS
# ----------------------------------------------------------------------

def parse_meta_datetime(value):
    if not value:
        return None

    value = value.replace("Z", "+00:00")

    # Meta sometimes returns offsets like +0000 instead of +00:00
    if (
        len(value) >= 5
        and value[-5] in ("+", "-")
        and value[-3] != ":"
    ):
        value = value[:-2] + ":" + value[-2:]

    return datetime.fromisoformat(value)


def meta_get(path, params=None):
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"

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

        raise RuntimeError(
            "Meta API error "
            f"code={error.get('code')} "
            f"subcode={error.get('error_subcode')} "
            f"type={error.get('type')}: "
            f"{error.get('message')}"
        )

    if not response.ok:
        raise RuntimeError(
            f"Meta returned HTTP {response.status_code}"
        )

    return payload


# ----------------------------------------------------------------------
# --FACEBOOK LIVE DISCOVERY
# ----------------------------------------------------------------------

def get_live_videos():
    """
    Get all currently accessible LiveVideo objects for the Page.
    """

    rows = []
    after = None

    while True:
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

        if after:
            params["after"] = after

        payload = meta_get(
            f"{PAGE_ID}/live_videos",
            params=params,
        )

        rows.extend(payload.get("data", []))

        paging = payload.get("paging", {})
        after = paging.get("cursors", {}).get("after")

        if not paging.get("next") or not after:
            break

    return rows


# ----------------------------------------------------------------------
# --FACEBOOK 1-MINUTE VIEW METRIC
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
# --FIND TARGET SUNDAYS GATHERINGS
# ----------------------------------------------------------------------

def discover_sunday_lives(target_sunday):
    print(f"Target Sunday: {target_sunday}")
    print("Getting Facebook Live videos...")

    live_videos = get_live_videos()

    print(
        f"Found {len(live_videos)} accessible "
        "Facebook LiveVideo object(s)."
    )

    rows = []

    for live in live_videos:
        title = live.get("title") or ""

        # Only PCC Sunday Gathering broadcasts
        if not title.startswith("Sunday Gathering //"):
            continue

        broadcast_start = parse_meta_datetime(
            live.get("broadcast_start_time")
        )

        if not broadcast_start:
            print(
                f"  SKIPPED: {live.get('id')} "
                f"'{title}' — no broadcast_start_time"
            )
            continue

        broadcast_eastern = broadcast_start.astimezone(EASTERN)

        # Use actual broadcast date in Atlanta/New York time
        if broadcast_eastern.date() != target_sunday:
            continue

        video = live.get("video") or {}
        video_id = video.get("id")

        if not video_id:
            print(
                f"  SKIPPED: {live.get('id')} "
                f"'{title}' — no underlying Video ID"
            )
            continue

        gathering = title.split("//", 1)[1].strip()

        print(
            f"  LIVE: {video_id} "
            f"'{title}' "
            f"started {broadcast_eastern}"
        )

        views = get_one_minute_views(video_id)

        if views is None:
            print(
                f"  WARNING: no 1-minute view metric "
                f"returned for {video_id}"
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
            "live_video_id": live.get("id"),
            "title": title,
            "gathering": gathering,
            "sunday_date": target_sunday.isoformat(),
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

    return rows


# ----------------------------------------------------------------------
# --BIGQUERY MERGE
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


def merge_snapshot(bq, rows):
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

    ON t.video_id = s.video_id

    WHEN MATCHED THEN
      UPDATE SET
        live_video_id = s.live_video_id,
        title = s.title,
        gathering = s.gathering,
        sunday_date = s.sunday_date,
        one_minute_views = s.one_minute_views,
        broadcast_start_time = s.broadcast_start_time,
        planned_start_time = s.planned_start_time,
        creation_time = s.creation_time,
        status = s.status,
        snapshot_taken_at = CURRENT_TIMESTAMP()

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

    print(
        f"MERGED {len(rows)} row(s) "
        "into facebook_sunday_snapshot"
    )


# ----------------------------------------------------------------------
# --MAIN
# ----------------------------------------------------------------------

def main():
    if not ACCESS_TOKEN:
        print(
            "ERROR: FACEBOOK_PAGE_ACCESS_TOKEN "
            "environment variable is missing."
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Facebook Sunday Gathering snapshot"
    )

    parser.add_argument(
        "--date",
        help="Sunday date YYYY-MM-DD",
    )

    args = parser.parse_args()

    if args.date:
        target_sunday = datetime.strptime(
            args.date,
            "%Y-%m-%d",
        ).date()
    else:
        today_eastern = datetime.now(EASTERN).date()

        target_sunday = today_eastern - timedelta(
            days=(today_eastern.weekday() + 1) % 7
        )

    rows = discover_sunday_lives(target_sunday)

    if not rows:
        print(
            "\nERROR: No Facebook Sunday Gathering "
            f"Live videos found for {target_sunday}."
        )
        sys.exit(1)

    print("\n=== Facebook Online Attendance ===")

    for row in sorted(
        rows,
        key=lambda x: x["broadcast_start_time"],
    ):
        print(
            f"  {row['gathering']:<10} "
            f"{row['one_minute_views']:>8,} "
            "1-minute views "
            f"[{row['video_id']}]"
        )

    if len(rows) == 1:
        print(
            "\nWARNING: only ONE Sunday Gathering "
            "Facebook Live was found."
        )

    bq = bigquery.Client(project=PROJECT)

    merge_snapshot(bq, rows)

    print("\nDone.")


if __name__ == "__main__":
    main()
