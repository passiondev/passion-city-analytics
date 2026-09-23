#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
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

GRAPH_VERSION = "v25.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

METRIC = "total_video_60s_excludes_shorter_views"

EASTERN = ZoneInfo("America/New_York")

ACCESS_TOKEN = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")

# Normalized title prefix (lowercase, no spaces).
TITLE_PREFIX = "sundaygathering//"

# How far back past the target Sunday to keep paging. Lives can be
# created (scheduled) days ahead of broadcast, so leave some buffer.
LOOKBACK_DAYS = 14

# Safety cap so a pagination bug can't loop forever.
MAX_PAGES = 40

# Retry settings for transient Meta failures.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5

# Meta error codes worth retrying (temporary / rate limiting).
TRANSIENT_META_CODES = {1, 2, 4, 17, 32, 341, 613}

# Meta error code for invalid / expired access token.
AUTH_ERROR_CODE = 190


class MetaAuthError(RuntimeError):
    pass


VERBOSE = False


def log_verbose(*args):
    if VERBOSE:
        print(*args)


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------

def parse_meta_datetime(value):
    """
    Convert a Meta timestamp into a timezone-aware Python datetime.
    """

    if not value:
        return None

    value = value.replace("Z", "+00:00")

    # Meta returns +0000 instead of +00:00.
    if (
        len(value) >= 5
        and value[-5] in ("+", "-")
        and value[-3] != ":"
    ):
        value = value[:-2] + ":" + value[-2:]

    return datetime.fromisoformat(value)


def is_sunday_gathering(title):
    normalized = (title or "").lower().replace(" ", "")
    return normalized.startswith(TITLE_PREFIX)


def extract_gathering(title):
    if "//" in title:
        return title.split("//", 1)[1].strip()
    return title.strip()


def meta_get(path, params=None):
    """
    Authenticated GET to the Meta Graph API with retry on
    transient failures.
    """

    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=60,
            )
        except requests.RequestException as exc:
            last_error = RuntimeError(f"Network error calling Meta: {exc}")
            _sleep_before_retry(attempt, last_error)
            continue

        try:
            payload = response.json()
        except ValueError:
            last_error = RuntimeError(
                f"Meta returned HTTP {response.status_code} "
                "with a non-JSON response."
            )
            if response.status_code >= 500:
                _sleep_before_retry(attempt, last_error)
                continue
            raise last_error

        if "error" in payload:
            error = payload["error"]
            code = error.get("code")

            message = (
                "Meta API error "
                f"code={code} "
                f"subcode={error.get('error_subcode')} "
                f"type={error.get('type')}: "
                f"{error.get('message')}"
            )

            if code == AUTH_ERROR_CODE:
                raise MetaAuthError(message)

            if code in TRANSIENT_META_CODES:
                last_error = RuntimeError(message)
                _sleep_before_retry(attempt, last_error)
                continue

            raise RuntimeError(message)

        if response.status_code >= 500:
            last_error = RuntimeError(
                f"Meta returned HTTP {response.status_code}"
            )
            _sleep_before_retry(attempt, last_error)
            continue

        if not response.ok:
            raise RuntimeError(f"Meta returned HTTP {response.status_code}")

        return payload

    raise last_error


def _sleep_before_retry(attempt, error):
    if attempt >= MAX_RETRIES:
        return
    wait = RETRY_BACKOFF_SECONDS * attempt
    print(f"  RETRY {attempt}/{MAX_RETRIES - 1} in {wait}s: {error}")
    time.sleep(wait)


# ----------------------------------------------------------------------
# FACEBOOK LIVE DISCOVERY
# ----------------------------------------------------------------------

def get_live_videos(target_sunday):
    """
    Retrieve Facebook LiveVideo objects, newest first, stopping once
    we've paged past LOOKBACK_DAYS before the target Sunday.
    """

    cutoff = target_sunday - timedelta(days=LOOKBACK_DAYS)

    rows = []
    after = None

    for page in range(1, MAX_PAGES + 1):
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

        payload = meta_get("me/live_videos", params=params)

        batch = payload.get("data", [])
        rows.extend(batch)

        # Early exit: once the oldest item on this page is older than
        # the cutoff, there's nothing relevant further back.
        if batch:
            oldest = parse_meta_datetime(batch[-1].get("creation_time"))
            if oldest and oldest.astimezone(EASTERN).date() < cutoff:
                log_verbose(f"  Stopped paging at page {page} (past cutoff {cutoff}).")
                break

        paging = payload.get("paging", {})
        after = paging.get("cursors", {}).get("after")

        if not paging.get("next") or not after:
            break
    else:
        print(f"WARNING: hit MAX_PAGES ({MAX_PAGES}) while paging live videos.")

    return rows


# ----------------------------------------------------------------------
# FACEBOOK 1-MINUTE VIEW METRIC
# ----------------------------------------------------------------------

def get_one_minute_views(video_id):
    """
    Retrieve Facebook's lifetime 1-minute view metric for an
    underlying Video object.
    """

    payload = meta_get(
        f"{video_id}/video_insights",
        params={
            "metric": METRIC,
            "period": "lifetime",
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
# DISCOVER TARGET SUNDAY
# ----------------------------------------------------------------------

def discover_sunday_lives(target_sunday):
    """
    Returns (rows, failures) where failures is a list of
    (video_id, title, reason) tuples.
    """

    print(f"Target Sunday: {target_sunday}")
    print("Getting Facebook Live videos...")

    live_videos = get_live_videos(target_sunday)

    print(f"Scanned {len(live_videos)} Facebook LiveVideo object(s).")

    for live in live_videos:
        log_verbose(
            "  FOUND:",
            live.get("id"),
            "|",
            live.get("title"),
            "|",
            live.get("broadcast_start_time"),
        )

    rows = []
    failures = []
    seen_video_ids = set()

    for live in live_videos:
        title = live.get("title") or ""

        if not is_sunday_gathering(title):
            continue

        broadcast_start = parse_meta_datetime(live.get("broadcast_start_time"))

        if not broadcast_start:
            log_verbose(
                f"  SKIPPED: {live.get('id')} '{title}' — no broadcast_start_time"
            )
            continue

        broadcast_eastern = broadcast_start.astimezone(EASTERN)

        # Actual broadcast date in Eastern Time is ground truth.
        if broadcast_eastern.date() != target_sunday:
            continue

        # LiveVideo ID != Video ID used by video_insights.
        video_id = (live.get("video") or {}).get("id")

        if not video_id:
            failures.append((live.get("id"), title, "no underlying Video ID"))
            print(f"  SKIPPED: {live.get('id')} '{title}' — no underlying Video ID")
            continue

        if video_id in seen_video_ids:
            continue
        seen_video_ids.add(video_id)

        print(f"  MATCHED: {video_id} '{title}' started {broadcast_eastern}")

        try:
            views = get_one_minute_views(video_id)
        except MetaAuthError:
            raise
        except Exception as exc:
            failures.append((video_id, title, str(exc)))
            print(f"  ERROR: insights failed for {video_id}: {exc}")
            continue

        if views is None:
            failures.append((video_id, title, "no 1-minute view metric returned"))
            print(f"  WARNING: no 1-minute view metric returned for {video_id}")
            continue

        planned_start = parse_meta_datetime(live.get("planned_start_time"))
        creation_time = parse_meta_datetime(live.get("creation_time"))

        rows.append({
            "video_id": video_id,
            "live_video_id": live.get("id"),
            "title": title,
            "gathering": extract_gathering(title),
            "sunday_date": target_sunday.isoformat(),
            "one_minute_views": views,
            "broadcast_start_time": broadcast_start.isoformat(),
            "planned_start_time": planned_start.isoformat() if planned_start else None,
            "creation_time": creation_time.isoformat() if creation_time else None,
            "status": live.get("status"),
        })

    return rows, failures


# ----------------------------------------------------------------------
# BIGQUERY
# ----------------------------------------------------------------------

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{TABLE}` (
    video_id STRING NOT NULL,
    live_video_id STRING,
    title STRING,
    gathering STRING,
    sunday_date DATE,
    one_minute_views INT64,
    broadcast_start_time TIMESTAMP,
    planned_start_time TIMESTAMP,
    creation_time TIMESTAMP,
    status STRING,
    snapshot_taken_at TIMESTAMP
)
PARTITION BY sunday_date
CLUSTER BY gathering
"""

# CAST (not SAFE_CAST) on critical fields so bad data fails loudly.
# Optional timestamps stay NULL-safe because JSON_VALUE returns NULL
# for JSON null, and CAST(NULL AS ...) is fine.
UNPACK_SQL = """
SELECT
    JSON_VALUE(r, '$.video_id') AS video_id,
    JSON_VALUE(r, '$.live_video_id') AS live_video_id,
    JSON_VALUE(r, '$.title') AS title,
    JSON_VALUE(r, '$.gathering') AS gathering,
    CAST(JSON_VALUE(r, '$.sunday_date') AS DATE) AS sunday_date,
    CAST(JSON_VALUE(r, '$.one_minute_views') AS INT64) AS one_minute_views,
    CAST(JSON_VALUE(r, '$.broadcast_start_time') AS TIMESTAMP) AS broadcast_start_time,
    CAST(JSON_VALUE(r, '$.planned_start_time') AS TIMESTAMP) AS planned_start_time,
    CAST(JSON_VALUE(r, '$.creation_time') AS TIMESTAMP) AS creation_time,
    JSON_VALUE(r, '$.status') AS status
FROM UNNEST(JSON_QUERY_ARRAY(@rows_json)) AS r
"""

UPDATE_CLAUSE = """
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
"""

INSERT_CLAUSE = """
WHEN NOT MATCHED THEN
  INSERT (
    video_id, live_video_id, title, gathering, sunday_date,
    one_minute_views, broadcast_start_time, planned_start_time,
    creation_time, status, snapshot_taken_at
  )
  VALUES (
    s.video_id, s.live_video_id, s.title, s.gathering, s.sunday_date,
    s.one_minute_views, s.broadcast_start_time, s.planned_start_time,
    s.creation_time, s.status, CURRENT_TIMESTAMP()
  )
"""


def ensure_table(bq):
    bq.query(CREATE_TABLE_SQL).result()


def merge_snapshot(bq, rows, refresh):
    """
    Upsert Facebook records keyed on video_id.

    refresh=False (default): insert new videos only; existing
      snapshots stay frozen at their first captured value.
    refresh=True: also overwrite existing rows with current values.
    """

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("rows_json", "STRING", json.dumps(rows))
        ]
    )

    sql = f"""
    MERGE `{TABLE}` t
    USING ({UNPACK_SQL}) s
    ON t.video_id = s.video_id
    {UPDATE_CLAUSE if refresh else ""}
    {INSERT_CLAUSE}
    """

    job = bq.query(sql, job_config=config)
    job.result()

    affected = job.num_dml_affected_rows or 0
    mode = "refresh" if refresh else "freeze"
    print(
        f"MERGE ({mode}): {affected} row(s) written of {len(rows)} "
        "submitted into facebook_sunday_snapshot"
    )

    if not refresh and affected < len(rows):
        print(
            f"  NOTE: {len(rows) - affected} video(s) already had a snapshot "
            "and were left unchanged. Use --refresh to overwrite."
        )


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    global VERBOSE

    parser = argparse.ArgumentParser(
        description="Facebook Sunday Gathering 1-minute view snapshot"
    )
    parser.add_argument(
        "--date",
        help="Sunday date YYYY-MM-DD (default: most recent Sunday)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Overwrite existing snapshots with current lifetime values",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every live video scanned and every skip",
    )
    args = parser.parse_args()

    VERBOSE = args.verbose

    if not ACCESS_TOKEN:
        print("ERROR: FACEBOOK_PAGE_ACCESS_TOKEN environment variable is missing.")
        sys.exit(1)

    if args.date:
        target_sunday = datetime.strptime(args.date, "%Y-%m-%d").date()
        if target_sunday.weekday() != 6:
            print(f"WARNING: {target_sunday} is not a Sunday.")
    else:
        today_eastern = datetime.now(EASTERN).date()
        target_sunday = today_eastern - timedelta(
            days=(today_eastern.weekday() + 1) % 7
        )

    try:
        rows, failures = discover_sunday_lives(target_sunday)
    except MetaAuthError as exc:
        print(f"\nERROR: Facebook token rejected — refresh or replace it.\n  {exc}")
        sys.exit(1)

    if not rows:
        print(
            "\nERROR: No Facebook Sunday Gathering "
            f"Live videos with metrics found for {target_sunday}."
        )
        for video_id, title, reason in failures:
            print(f"  FAILED: {video_id} '{title}' — {reason}")
        sys.exit(1)

    print("\n=== Facebook Online Attendance ===")

    for row in sorted(rows, key=lambda x: x["broadcast_start_time"]):
        print(
            f"  {row['gathering']:<12}"
            f"{row['one_minute_views']:>8,} 1-minute views "
            f"[video_id={row['video_id']}]"
        )

    if len(rows) == 1:
        print("\nWARNING: only ONE Sunday Gathering Facebook Live was found.")

    bq = bigquery.Client(project=PROJECT)
    ensure_table(bq)
    merge_snapshot(bq, rows, refresh=args.refresh)

    if failures:
        print(f"\nPARTIAL: {len(failures)} video(s) failed:")
        for video_id, title, reason in failures:
            print(f"  FAILED: {video_id} '{title}' — {reason}")
        sys.exit(2)

    print("\nDone.")


if __name__ == "__main__":
    main()
