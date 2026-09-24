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

TABLE = (
    f"{PROJECT}.{DATASET}."
    "facebook_sunday_snapshot"
)

PAGE_ID = "192924437428798"

GRAPH_VERSION = "v25.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

METRIC = "total_video_60s_excludes_shorter_views"

EASTERN = ZoneInfo("America/New_York")

ACCESS_TOKEN = os.environ.get(
    "FACEBOOK_PAGE_ACCESS_TOKEN"
)


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
            "Meta API error "
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

    value = value.replace(
        "Z",
        "+00:00",
    )

    # Convert offsets like +0000 to +00:00.
    if (
        len(value) >= 5
        and value[-5] in ("+", "-")
        and value[-3] != ":"
    ):
        value = (
            value[:-2]
            + ":"
            + value[-2:]
        )

    return datetime.fromisoformat(value)


def meta_get(
    path_or_url,
    params=None,
):
    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        url = (
            f"{GRAPH_BASE}/"
            f"{path_or_url.lstrip('/')}"
        )

    headers = {
        "Authorization": (
            f"Bearer {ACCESS_TOKEN}"
        )
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
            "Meta returned "
            f"HTTP {response.status_code} "
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
            subcode=error.get(
                "error_subcode"
            ),
            error_type=error.get(
                "type"
            ),
        )

    if not response.ok:
        raise RuntimeError(
            "Meta returned HTTP "
            f"{response.status_code}"
        )

    return payload


# ----------------------------------------------------------------------
# FACEBOOK LIVE DISCOVERY
# ----------------------------------------------------------------------

def get_live_videos():
    """
    Retrieve every LiveVideo object currently exposed
    through the Page's /live_videos edge.
    """

    live_videos = []
    seen_ids = set()

    url = (
        f"{GRAPH_BASE}/"
        f"{PAGE_ID}/live_videos"
    )

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
        print(
            f"Reading Live Video "
            f"page {page_number}..."
        )

        payload = meta_get(
            url,
            params=params,
        )

        videos = payload.get(
            "data",
            [],
        )

        for live in videos:
            live_id = live.get("id")

            if (
                live_id
                and live_id not in seen_ids
            ):
                seen_ids.add(live_id)
                live_videos.append(live)

        print(
            f"  Found {len(videos)} "
            "on this page "
            f"({len(live_videos)} "
            "total so far)"
        )

        url = (
            payload
            .get("paging", {})
            .get("next")
        )

        # paging.next already contains
        # its paging parameters.
        params = None

        page_number += 1

    return live_videos


# ----------------------------------------------------------------------
# FACEBOOK 1-MINUTE VIEWS
# ----------------------------------------------------------------------

def get_one_minute_views(
    video_id,
):
    payload = meta_get(
        f"{video_id}/video_insights",
        params={
            "metric": METRIC
        },
    )

    for metric in payload.get(
        "data",
        [],
    ):
        if metric.get("name") != METRIC:
            continue

        values = metric.get(
            "values",
            [],
        )

        if not values:
            return None

        value = values[0].get(
            "value"
        )

        if value is None:
            return None

        return int(value)

    return None


# ----------------------------------------------------------------------
# FIND TARGET SUNDAY
# ----------------------------------------------------------------------

def discover_sunday_lives(
    target_sunday,
):
    print(
        f"Target Sunday: "
        f"{target_sunday}"
    )

    print(
        "Getting Facebook Live videos..."
    )

    live_videos = get_live_videos()

    print(
        "\nScanned "
        f"{len(live_videos)} "
        "Facebook LiveVideo object(s)."
    )

    rows = []

    for live in live_videos:
        live_id = live.get("id")

        title = (
            live.get("title")
            or ""
        )

        broadcast_start = (
            parse_meta_datetime(
                live.get(
                    "broadcast_start_time"
                )
            )
        )

        print(
            "  FOUND:",
            live_id,
            "|",
            title,
            "|",
            live.get(
                "broadcast_start_time"
            ),
        )

        # Only Sunday Gathering streams.
        if not title.startswith(
            "Sunday Gathering //"
        ):
            continue

        if not broadcast_start:
            print(
                "    SKIPPED - "
                "no broadcast_start_time"
            )
            continue

        broadcast_eastern = (
            broadcast_start
            .astimezone(EASTERN)
        )

        # The actual broadcast date in
        # Eastern Time is our ground truth.
        if (
            broadcast_eastern.date()
            != target_sunday
        ):
            continue

        video_object = (
            live.get("video")
            or {}
        )

        video_id = (
            video_object.get("id")
        )

        if not video_id:
            print(
                "    SKIPPED - "
                "no underlying Video ID"
            )
            continue

        if "//" in title:
            gathering = (
                title
                .split("//", 1)[1]
                .strip()
            )
        else:
            gathering = title

        print(
            f"    MATCHED "
            f"{gathering}"
        )

        try:
            views = (
                get_one_minute_views(
                    video_id
                )
            )

        except MetaAPIError as error:
            # Meta sometimes stops exposing
            # individual Live/Video objects.
            #
            # Skip code 100/subcode 33 rather
            # than failing the whole pipeline.
            if (
                error.code == 100
                and error.subcode == 33
            ):
                print(
                    "    SKIPPED - "
                    "Video object is no longer "
                    "accessible through Meta API."
                )
                continue

            # Authentication and other real API
            # errors should still fail the job.
            raise

        if views is None:
            print(
                "    SKIPPED - "
                "1-minute metric returned "
                "no value."
            )
            continue

        planned_start = (
            parse_meta_datetime(
                live.get(
                    "planned_start_time"
                )
            )
        )

        creation_time = (
            parse_meta_datetime(
                live.get(
                    "creation_time"
                )
            )
        )

        row = {
            "video_id": video_id,

            "live_video_id":
                live_id,

            "title":
                title,

            "gathering":
                gathering,

            "sunday_date":
                target_sunday.isoformat(),

            "one_minute_views":
                views,

            "broadcast_start_time":
                broadcast_start.isoformat(),

            "planned_start_time":
                (
                    planned_start
                    .isoformat()
                    if planned_start
                    else None
                ),

            "creation_time":
                (
                    creation_time
                    .isoformat()
                    if creation_time
                    else None
                ),

            "status":
                live.get("status"),
        }

        rows.append(row)

        print(
            "    1-Minute Views:",
            views,
        )

    return rows


# ----------------------------------------------------------------------
# BIGQUERY
# ----------------------------------------------------------------------

UNPACK_SQL = """
SELECT
    JSON_VALUE(
        r,
        '$.video_id'
    ) AS video_id,

    JSON_VALUE(
        r,
        '$.live_video_id'
    ) AS live_video_id,

    JSON_VALUE(
        r,
        '$.title'
    ) AS title,

    JSON_VALUE(
        r,
        '$.gathering'
    ) AS gathering,

    SAFE_CAST(
        JSON_VALUE(
            r,
            '$.sunday_date'
        )
        AS DATE
    ) AS sunday_date,

    SAFE_CAST(
        JSON_VALUE(
            r,
            '$.one_minute_views'
        )
        AS INT64
    ) AS one_minute_views,

    SAFE_CAST(
        JSON_VALUE(
            r,
            '$.broadcast_start_time'
        )
        AS TIMESTAMP
    ) AS broadcast_start_time,

    SAFE_CAST(
        JSON_VALUE(
            r,
            '$.planned_start_time'
        )
        AS TIMESTAMP
    ) AS planned_start_time,

    SAFE_CAST(
        JSON_VALUE(
            r,
            '$.creation_time'
        )
        AS TIMESTAMP
    ) AS creation_time,

    JSON_VALUE(
        r,
        '$.status'
    ) AS status

FROM UNNEST(
    JSON_EXTRACT_ARRAY(
        @rows_json
    )
) AS r
"""


def merge_snapshot(
    bq,
    rows,
):
    config = (
        bigquery.QueryJobConfig(
            query_parameters=[
                bigquery
                .ScalarQueryParameter(
                    "rows_json",
                    "STRING",
                    json.dumps(rows),
                )
            ]
        )
    )

    sql = f"""
    MERGE `{TABLE}` t

    USING (
        {UNPACK_SQL}
    ) s

    ON t.video_id = s.video_id

    WHEN MATCHED THEN
      UPDATE SET

        live_video_id =
            s.live_video_id,

        title =
            s.title,

        gathering =
            s.gathering,

        sunday_date =
            s.sunday_date,

        one_minute_views =
            s.one_minute_views,

        broadcast_start_time =
            s.broadcast_start_time,

        planned_start_time =
            s.planned_start_time,

        creation_time =
            s.creation_time,

        status =
            s.status,

        snapshot_taken_at =
            CURRENT_TIMESTAMP()

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
        "\nMERGED "
        f"{len(rows)} "
        "row(s) into "
        "facebook_sunday_snapshot"
    )


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    if not ACCESS_TOKEN:
        print(
            "ERROR: "
            "FACEBOOK_PAGE_ACCESS_TOKEN "
            "environment variable "
            "is missing."
        )

        return 1

    parser = argparse.ArgumentParser(
        description=(
            "Facebook Sunday Gathering "
            "1-minute view snapshot"
        )
    )

    parser.add_argument(
        "--date",
        help=(
            "Sunday date YYYY-MM-DD "
            "(default: most recent Sunday)"
        ),
    )

    args = parser.parse_args()

    if args.date:
        target_sunday = (
            datetime.strptime(
                args.date,
                "%Y-%m-%d",
            )
            .date()
        )

    else:
        today_eastern = (
            datetime.now(EASTERN)
            .date()
        )

        target_sunday = (
            today_eastern
            - timedelta(
                days=(
                    today_eastern.weekday()
                    + 1
                )
                % 7
            )
        )

    rows = discover_sunday_lives(
        target_sunday
    )

    # --------------------------------------------------------------
    # IMPORTANT:
    # No accessible Meta rows is NOT considered a workflow failure.
    #
    # Meta may stop exposing older LiveVideo/Video objects.
    # Existing BigQuery data must remain untouched.
    # --------------------------------------------------------------

    if not rows:
        print(
            "\nWARNING: Meta currently "
            "returned no accessible "
            "Facebook Sunday Gathering "
            "videos with metrics for "
            f"{target_sunday}."
        )

        print(
            "No BigQuery changes were made."
        )

        print(
            "Any previously captured "
            "snapshot remains unchanged."
        )

        print("\nDone.")

        return 0

    print(
        "\n=== Facebook Online Attendance ==="
    )

    rows.sort(
        key=lambda row: (
            row[
                "broadcast_start_time"
            ]
        )
    )

    for row in rows:
        print(
            f"  {row['gathering']:<12}"
            f"{row['one_minute_views']:>8,} "
            "1-minute views "
            f"[video_id="
            f"{row['video_id']}]"
        )

    if len(rows) == 1:
        print(
            "\nWARNING: only ONE "
            "Sunday Gathering Facebook "
            "Live was accessible."
        )

    bq = bigquery.Client(
        project=PROJECT
    )

    merge_snapshot(
        bq,
        rows,
    )

    print("\nDone.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
