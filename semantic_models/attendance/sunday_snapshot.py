#!/usr/bin/env python3
"""
sunday_snapshot.py — Monday-morning Sunday Gathering snapshot for BigQuery.

v5 — skip future-scheduled videos (2026-08-24):
  * Videos are now checked via `status.publishAt`. If present, the video
    is still scheduled for a FUTURE release and is skipped. This fixes a
    bug where a scheduled video (already carrying a `snippet.publishedAt`
    timestamp from the API even though it isn't out yet) was slipping into
    the Sunday window and getting treated as this week's real upload --
    causing ambiguity downstream (e.g. SermonVideoId in Power BI picking
    the wrong video when SELECTEDVALUE() saw two candidates for the same
    day).
  * Deliberately does NOT filter on `status.privacyStatus` -- an earlier
    version of this fix tried that and it broke livestream detection,
    since PCC's actual service livestreams are routinely 'unlisted' or
    'private' by design, not 'public'. Only status.publishAt reliably
    distinguishes "still scheduled, not really out" from "intentionally
    non-public, but already live."

v4 — full Monday coverage (attendance numbers + sermon thumbnail):
  * LIVESTREAMS whose liveStreamingDetails.actualStartTime falls on the
    target Sunday -> merged into `sunday_snapshot` (attendance fallback)
    AND `video_titles`.
  * ALL OTHER videos published in the Sunday window (sermon edit, VOD
    reuploads, etc.) -> merged into `video_titles` ONLY, so downstream
    lookups (e.g. the dashboard's sermon thumbnail) resolve on Monday.
    They never enter the attendance path: no snapshot row, was_live=FALSE.

  Why not playlist dates for livestream discovery: private videos have no
  videoPublishedAt, so playlist filtering misses them (learned 2026-07-06).
  Stream time (actualStartTime) is the ground truth and exists on private
  archives. Public uploads (sermon edit) DO have videoPublishedAt, so the
  Sunday-window check works for them.

Usage:
  python3 ~/sunday_snapshot.py                     # auto: most recent Sunday
  python3 ~/sunday_snapshot.py --date 2026-07-05   # specific Sunday
  python3 ~/sunday_snapshot.py --ids "ID1,ID2"     # manual: treat as
                                                   #  livestreams (quoted,
                                                   #  comma-separated)
  python3 ~/sunday_snapshot.py --ids "ID1" --force-live
        # mark supplied IDs live even if API omits liveStreamingDetails

Requirements (same env as update_video_titles.py):
  python3 -m pip install google-api-python-client google-auth-oauthlib google-cloud-bigquery
  ~/client_secrets.json  (OAuth Desktop client, tech@268generation.com)
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
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
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

RECENT_UPLOADS_TO_SCAN = 50


def is_gathering_title(title: str) -> bool:
    """Must mirror the WHERE clause in v_gathering_views."""
    return title.startswith("Sunday Gathering //") or "FULL GATHERING" in title


# ----------------------------------------------------------------------
# AUTH
# ----------------------------------------------------------------------
def get_youtube():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


# ----------------------------------------------------------------------
# FETCH: full video data for a list of IDs
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
            rows.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "published_at": item["snippet"]["publishedAt"][:10],  # '%Y-%m-%d'
                "views": int(item.get("statistics", {}).get("viewCount", 0)),
                "was_live": force_live or bool(actual_start),
                "stream_date": actual_start[:10] if actual_start else None,
            })
    return rows


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


# ----------------------------------------------------------------------
# WRITE: MERGE via a single JSON string parameter
# ----------------------------------------------------------------------
UNPACK_SQL = """
  SELECT
    JSON_VALUE(r, '$.video_id')                AS video_id,
    JSON_VALUE(r, '$.title')                   AS title,
    JSON_VALUE(r, '$.published_at')            AS published_at,
    CAST(JSON_VALUE(r, '$.views') AS INT64)    AS views,
    CAST(JSON_VALUE(r, '$.was_live') AS BOOL)  AS was_live
  FROM UNNEST(JSON_EXTRACT_ARRAY(@rows_json)) AS r
"""


def _job_config(rows: list[dict]) -> bigquery.QueryJobConfig:
    payload = [
        {k: r[k] for k in ("video_id", "title", "published_at", "views", "was_live")}
        for r in rows
    ]
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
      views = s.views, was_live = s.was_live,
      snapshot_taken_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT
      (video_id, title, published_at, views, was_live, snapshot_taken_at)
      VALUES (s.video_id, s.title, s.published_at, s.views, s.was_live,
              CURRENT_TIMESTAMP())
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
    args = ap.parse_args()

    if args.date:
        sunday = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = date.today()
        sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    print(f"Target Sunday: {sunday}")

    yt = get_youtube()

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

    print("\n=== Attendance (snapshot + titles) ===")
    if livestreams:
        for r in livestreams:
            flag = "LIVE" if r["was_live"] else "not-live (view will EXCLUDE this)"
            print(f"  {r['video_id']}  {r['views']:>8,} views  [{flag}]  {r['title']}")
    else:
        print("  (none)")
    if len(livestreams) == 1:
        print("  NOTE: only ONE livestream found — a typical Sunday has two")
        print("  services. Check YouTube Studio; use --ids if one is missing.")

    print("\n=== Titles only (thumbnails / lookups; NOT attendance) ===")
    if other_uploads:
        for r in other_uploads:
            print(f"  {r['video_id']}  '{r['title']}'  published {r['published_at']}")
    else:
        print("  (none — if the sermon edit isn't published yet, its")
        print("  thumbnail will resolve after the next run that finds it)")

    bq = bigquery.Client(project=PROJECT)
    merge_snapshot(bq, livestreams)
    merge_titles(bq, livestreams, "livestreams")
    merge_titles(bq, other_uploads, "uploads")

    print("\nDone. Refresh the Dataflow, then Power BI Desktop.")


if __name__ == "__main__":
    main()
