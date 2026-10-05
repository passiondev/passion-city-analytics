#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.cloud import bigquery

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
PROJECT = "bigquery-test-469018"
DATASET = "youtube_passion_city_church"
SNAPSHOT_TABLE = f"{PROJECT}.{DATASET}.sunday_snapshot"
TITLES_TABLE = f"{PROJECT}.{DATASET}.video_titles"

CLIENT_SECRETS = os.path.expanduser("~/client_secrets.json")
TOKEN_FILE = os.path.expanduser("~/token_sunday_snapshot.json")
SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # NEW: live vs on-demand split
]

RECENT_UPLOADS_TO_SCAN = 50

# views_source values written to sunday_snapshot
SRC_LIVE = "analytics_live"                  # final: LIVE-only views from Analytics API
SRC_PROVISIONAL = "data_api_total_provisional"  # Analytics not ready yet; total views, will be overwritten
SRC_TOTAL = "data_api_total"                 # non-live rows / titles


def is_gathering_title(title: str) -> bool:
    """Must mirror the WHERE clause in v_gathering_views."""
    return title.startswith("Sunday Gathering //") or "FULL GATHERING" in title


# ----------------------------------------------------------------------
# AUTH  (returns Data API + Analytics API clients)
# ----------------------------------------------------------------------
def get_clients():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                # e.g. invalid_scope after adding the analytics scope
                print(f"Token refresh failed ({e}); re-consent required.")
                if os.environ.get("GITHUB_ACTIONS"):
                    sys.exit("Cannot re-consent in GitHub Actions. Re-auth locally "
                             "and update the YOUTUBE_TOKEN_JSON secret.")
                creds = None
        if not creds or not creds.valid:
            print(">>> Log in as tech@, pick PASSION CITY CHURCH, tick ALL permission boxes.")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    yt = build("youtube", "v3", credentials=creds)
    yta = build("youtubeAnalytics", "v2", credentials=creds)
    return yt, yta


# ----------------------------------------------------------------------
# FETCH: full video data for a list of IDs  (Data API)
# ----------------------------------------------------------------------
def fetch_video_data(yt, video_ids: list[str], force_live: bool = False) -> list[dict]:
    rows = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = yt.videos().list(
            part="snippet,statistics,liveStreamingDetails,status",
            id=",".join(batch),
        ).execute()
        returned = {item["id"] for item in resp.get("items", [])}
        for m in set(batch) - returned:
            print(f"  WARNING: API returned nothing for {m} (permissions? deleted?)")
        for item in resp.get("items", []):
            status = item.get("status", {})
            publish_at = status.get("publishAt")  # only set for future-scheduled videos

            # Skip only videos still scheduled for a FUTURE release. YouTube
            # sets status.publishAt to a future timestamp for these; it is
            # NOT set on normal public/unlisted/private uploads once they've
            # actually gone out. Do NOT filter on privacyStatus alone --
            # livestreams here are routinely 'unlisted' or 'private' by
            # design and must still count toward attendance.
            if publish_at:
                print(
                    f"  SKIPPED (scheduled for {publish_at}): {item['id']}  "
                    f"'{item['snippet']['title']}'"
                )
                continue

            live_details = item.get("liveStreamingDetails", {})
            actual_start = live_details.get("actualStartTime")  # None for VODs
            total = int(item.get("statistics", {}).get("viewCount", 0))
            rows.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"][:10],  # '%Y-%m-%d'
                "views": total,          # replaced with LIVE views in apply_live_views()
                "total_views": total,    # NEW: always the Data API odometer (live + replay)
                "views_source": SRC_TOTAL,
                "was_live": force_live or bool(actual_start),
                "stream_date": actual_start[:10] if actual_start else None,
            })
    return rows


# ----------------------------------------------------------------------
# LIVE VIEWS  (Analytics API: liveOrOnDemand split)
# ----------------------------------------------------------------------
def get_live_views(yta, video_id: str, stream_date: str):
    """Return LIVE-only views, or None if Analytics hasn't processed them yet.

    Auth/permission errors (401/403) are raised on purpose so the workflow
    fails loudly instead of silently falling back to inflated totals.
    """
    start = (date.fromisoformat(stream_date) - timedelta(days=1)).isoformat()
    try:
        resp = yta.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=date.today().isoformat(),
            metrics="views",
            dimensions="liveOrOnDemand",
            filters=f"video=={video_id}",
        ).execute()
    except HttpError as e:
        if e.resp.status in (401, 403):
            raise
        print(f"  WARNING: Analytics query failed for {video_id}: {e}")
        return None
    for row in resp.get("rows", []):
        if row[0] == "LIVE" and int(row[1]) > 0:
            return int(row[1])
    return None


def apply_live_views(yta, rows: list[dict]):
    for r in rows:
        if not r["was_live"]:
            continue
        stream_date = r["stream_date"] or r["published_at"]
        live = get_live_views(yta, r["video_id"], stream_date)
        if live is not None:
            r["views"] = live
            r["views_source"] = SRC_LIVE
        else:
            r["views_source"] = SRC_PROVISIONAL
            print(f"  NOTE: LIVE views not ready for {r['video_id']} -- "
                  f"writing provisional total; a later run will overwrite it.")


# ----------------------------------------------------------------------
# DISCOVERY: recent uploads -> videos.list -> split into two groups
#   livestreams  : actualStartTime on the target Sunday (attendance)
#   other_uploads: published in Sunday window, not livestreams (titles only)
# ----------------------------------------------------------------------
def discover_sunday_videos(yt, sunday: date):
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        print("WARNING: channels.list(mine=True) returned no channel.")
        print('Re-run with --ids "ID1,ID2" using IDs from YouTube Studio.')
        return [], []
    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Uploads playlist: {uploads_playlist}")

    recent_ids, page_token = [], None
    while len(recent_ids) < RECENT_UPLOADS_TO_SCAN:
        resp = yt.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        recent_ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    recent_ids = recent_ids[:RECENT_UPLOADS_TO_SCAN]
    print(f"Scanning {len(recent_ids)} recent uploads around {sunday}...")

    all_data = fetch_video_data(yt, recent_ids)

    # Sunday window for non-live uploads: Sunday and Monday (covers sermon
    # edits published Sunday night ET, which can be Monday UTC).
    window = {sunday.isoformat(), (sunday + timedelta(days=1)).isoformat()}

    livestreams, other_uploads = [], []
    for r in all_data:
        if r["was_live"] and r["stream_date"] == sunday.isoformat():
            if is_gathering_title(r["title"]):
                print(f"  LIVESTREAM: {r['video_id']}  '{r['title']}'")
                livestreams.append(r)
            else:
                print(f"  skipped live (title mismatch): {r['video_id']}  '{r['title']}'")
        elif not r["was_live"] and r["published_at"] in window:
            print(f"  UPLOAD (titles only): {r['video_id']}  '{r['title']}'")
            other_uploads.append(r)

    return livestreams, other_uploads


def backfill_ids(bq: bigquery.Client) -> list[str]:
    """Every livestream already in sunday_snapshot -- no discovery needed."""
    sql = f"SELECT DISTINCT video_id FROM `{SNAPSHOT_TABLE}` WHERE was_live"
    return [r.video_id for r in bq.query(sql).result()]


# ----------------------------------------------------------------------
# WRITE: MERGE via a single JSON string parameter
# ----------------------------------------------------------------------
UNPACK_SQL = """
  SELECT
    JSON_VALUE(r, '$.video_id')                     AS video_id,
    JSON_VALUE(r, '$.title')                        AS title,
    JSON_VALUE(r, '$.published_at')                 AS published_at,
    CAST(JSON_VALUE(r, '$.views') AS INT64)         AS views,
    CAST(JSON_VALUE(r, '$.total_views') AS INT64)   AS total_views,
    JSON_VALUE(r, '$.views_source')                 AS views_source,
    CAST(JSON_VALUE(r, '$.was_live') AS BOOL)       AS was_live
  FROM UNNEST(JSON_EXTRACT_ARRAY(@rows_json)) AS r
"""

PAYLOAD_KEYS = ("video_id", "title", "published_at", "views",
                "total_views", "views_source", "was_live")


def _job_config(rows: list[dict]) -> bigquery.QueryJobConfig:
    payload = [{k: r[k] for k in PAYLOAD_KEYS} for r in rows]
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("rows_json", "STRING", json.dumps(payload))
        ]
    )


def merge_titles(bq: bigquery.Client, rows: list[dict], label: str):
    if not rows:
        return
    sql = f"""
    MERGE `{TITLES_TABLE}` t
    USING (SELECT video_id, title, published_at FROM ({UNPACK_SQL})) s
    ON t.video_id = s.video_id
    WHEN MATCHED THEN UPDATE SET title = s.title, published_at = s.published_at
    WHEN NOT MATCHED THEN INSERT (video_id, title, published_at)
      VALUES (s.video_id, s.title, s.published_at)
    """
    bq.query(sql, job_config=_job_config(rows)).result()
    print(f"MERGED {len(rows)} row(s) into video_titles ({label})")


def merge_snapshot(bq: bigquery.Client, rows: list[dict]):
    if not rows:
        return
    sql = f"""
    MERGE `{SNAPSHOT_TABLE}` t
    USING ({UNPACK_SQL}) s
    ON t.video_id = s.video_id
    WHEN MATCHED THEN UPDATE SET
      title = s.title, published_at = s.published_at,
      views = s.views, total_views = s.total_views, views_source = s.views_source,
      was_live = s.was_live,
      snapshot_taken_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT
      (video_id, title, published_at, views, total_views, views_source,
       was_live, snapshot_taken_at)
      VALUES (s.video_id, s.title, s.published_at, s.views, s.total_views,
              s.views_source, s.was_live, CURRENT_TIMESTAMP())
    """
    bq.query(sql, job_config=_job_config(rows)).result()
    print(f"MERGED {len(rows)} row(s) into sunday_snapshot")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Sunday Gathering Monday snapshot")
    ap.add_argument("--date", help="Sunday date YYYY-MM-DD (default: most recent Sunday)")
    ap.add_argument("--ids", help='Comma-separated video IDs, quoted: --ids "ID1,ID2"')
    ap.add_argument("--force-live", action="store_true",
                    help="Mark supplied --ids as live even if API omits liveStreamingDetails")
    ap.add_argument("--backfill", action="store_true",
                    help="Re-pull LIVE views for every livestream already in sunday_snapshot")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be written, but don't touch BigQuery")
    args = ap.parse_args()

    yt, yta = get_clients()
    bq = bigquery.Client(project=PROJECT)

    if args.backfill:
        ids = backfill_ids(bq)
        print(f"BACKFILL: {len(ids)} livestream(s) found in sunday_snapshot")
        livestreams = fetch_video_data(yt, ids, force_live=True)
        other_uploads = []
    else:
        if args.date:
            sunday = datetime.strptime(args.date, "%Y-%m-%d").date()
        else:
            today = date.today()
            sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        print(f"Target Sunday: {sunday}")

        if args.ids:
            ids = [v.strip() for v in args.ids.split(",") if v.strip()]
            print(f"Using supplied IDs (treated as livestreams): {ids}")
            livestreams = fetch_video_data(yt, ids, force_live=args.force_live)
            other_uploads = []
        else:
            livestreams, other_uploads = discover_sunday_videos(yt, sunday)

    if not livestreams and not other_uploads:
        print("\nNothing found for that Sunday. If videos exist in YouTube")
        print('Studio, re-run with:  python3 ~/sunday_snapshot.py --ids "ID1,ID2"')
        sys.exit(1)

    apply_live_views(yta, livestreams)

    print("\n=== Attendance (snapshot + titles) ===")
    if livestreams:
        for r in sorted(livestreams, key=lambda x: x["stream_date"] or x["published_at"]):
            flag = "LIVE" if r["was_live"] else "not-live (view will EXCLUDE this)"
            print(f"  {r['stream_date'] or r['published_at']}  {r['video_id']}  "
                  f"{r['views']:>8,} views (total {r['total_views']:,})  "
                  f"[{flag} / {r['views_source']}]  {r['title']}")
    else:
        print("  (none)")
    if not args.backfill and len(livestreams) == 1:
        print("  NOTE: only ONE livestream found — a typical Sunday has two")
        print("  services. Check YouTube Studio; use --ids if one is missing.")

    print("\n=== Titles only (thumbnails / lookups; NOT attendance) ===")
    if other_uploads:
        for r in other_uploads:
            print(f"  {r['video_id']}  '{r['title']}'  published {r['published_at']}")
    else:
        print("  (none — if the sermon edit isn't published yet, its")
        print("  thumbnail will resolve after the next run that finds it)")

    if args.dry_run:
        print("\nDRY RUN — nothing written to BigQuery.")
        return

    merge_snapshot(bq, livestreams)
    merge_titles(bq, livestreams, "livestreams")
    merge_titles(bq, other_uploads, "uploads")

    print("\nDone. Refresh the Dataflow, then Power BI Desktop.")


if __name__ == "__main__":
    main()
