# Sunday Snapshot — Pipeline Runbook

## What this does

Every Sunday at 9:00 PM Eastern (1:00 AM UTC Monday), a GitHub Actions
workflow runs `sunday_snapshot.py`, which:

1. Pulls YouTube livestream view counts and sermon-clip titles for that
   Sunday
2. Skips any video still scheduled for future release (so a not-yet-public
   upload never gets mistaken for the week's real content)
3. Writes the results into two BigQuery tables — `sunday_snapshot` and
   `video_titles` — via `MERGE`, so re-running it never creates duplicates
4. Powers the Online Attendance card and sermon thumbnail on the
   SundayMetrics Power BI dashboard

**Repo location:** `passion-city-analytics`
- Script: `semantic_models/attendance/sunday_snapshot.py`
- Workflow: `.github/workflows/sunday-snapshot.yml`
- Can be triggered manually anytime via the **Actions** tab → *Sunday
  Snapshot* → **Run workflow**

## Authentication — two separate systems

| | YouTube Data API | BigQuery |
|---|---|---|
| **Auth type** | OAuth refresh token (human-consent based) | Service account (robot identity) |
| **GitHub Secrets used** | `YOUTUBE_TOKEN_JSON`, `YOUTUBE_CLIENT_SECRETS` | `GCP_SERVICE_ACCOUNT_JSON` |
| **Tied to Testing/Production OAuth status?** | Yes — this is the ongoing risk | No — not applicable |
| **Expires on its own?** | Possibly — Testing-mode consent has a known ~7-day refresh-token risk window | No — stays valid indefinitely unless manually revoked/rotated |

**Current state (as of Aug 2026):** the Google Cloud OAuth consent screen
for project `bigquery-test-469018` is intentionally left in **Testing**
status (not Production) — this was a deliberate choice, not an oversight,
made to avoid the extra verification/rollout work of publishing while
still validating the pipeline. `tech@268generation.com` is the sole test
user. In practice, weekly script runs have kept the refresh token alive
without issue so far, but Testing-mode tokens are not guaranteed
long-lived — hence the failure-alert setup below.

## If you get a GitHub Actions failure email

GitHub automatically emails whoever created the workflow (currently:
Sandeep) when a scheduled or manual run fails. The workflow itself also
tries to diagnose the cause before it fails, via a "Check for auth
failure" step that greps the run log for known auth-error signatures.

**Step 1 — Open the failed run and read the error annotation**
1. Go to the repo → **Actions** tab → click the failed run
2. Look at the **"Check for auth failure"** step — it will say one of:
   - `"YouTube OAuth token has expired (Testing-mode consent, ~7-day
     lifetime). Re-authenticate locally to regenerate
     token_sunday_snapshot.json, then update the YOUTUBE_TOKEN_JSON
     secret."` → go to **Fix A** below
   - `"Script failed for a non-auth reason — see run.log above for
     details."` → go to **Fix B** below

**Step 2 — Download the full log if needed**
The complete output is also attached as a downloadable artifact
("run-log") on the same run page, under **Artifacts**, in case the
inline log is truncated.

### Fix A — YouTube OAuth token expired

This means the refresh token GitHub was using no longer works, most
likely because the Testing-mode consent window lapsed.

1. On your local machine, run the script manually once:
   ```bash
   python3 ~/Sunday_Dashboard/sunday_snapshot.py
   ```
   *(Note: the real, active token file is always
   `~/token_sunday_snapshot.json` — the home directory, not wherever the
   script itself lives. If a stray/old copy exists elsewhere, ignore it.)*
2. If the token has genuinely expired, this will open a browser window
   asking you to log in as `tech@268generation.com` and re-consent.
   Complete that flow — it will silently rewrite
   `~/token_sunday_snapshot.json` with a fresh token.
3. Copy the refreshed token contents:
   ```bash
   cat ~/token_sunday_snapshot.json
   ```
4. Go to the GitHub repo → **Settings → Secrets and variables → Actions**
5. Click on `YOUTUBE_TOKEN_JSON` → **Update** → paste the new contents →
   **Update secret**
6. Re-run the failed workflow (or trigger a fresh manual run via
   `workflow_dispatch`) to confirm it now succeeds.

**Long-term fix (not yet done):** publishing the OAuth consent screen to
Production removes this expiry risk entirely. This was deliberately
deferred — revisit if Testing-mode failures start happening often, or
once comfortable moving out of the testing phase. May require IT/Wesley
involvement given the project's prior `org_internal` OAuth restriction.

### Fix B — Non-auth failure

Since BigQuery auth is now handled by a dedicated service account (not
tied to any human login or expiry), it should not be the cause of an
unexplained failure. More likely causes:
- A transient YouTube API or BigQuery outage/rate limit — often
  resolves on its own; just re-run the workflow
- A code-level bug (e.g., an unexpected API response shape) — read the
  full `run.log` artifact for a Python traceback and treat like any
  other script bug
- The BigQuery service account's key was rotated or revoked (rare,
  would only happen if IT does a deliberate security cleanup) — would
  need a new key generated and `GCP_SERVICE_ACCOUNT_JSON` updated the
  same way as Fix A above, but for that secret

## Idempotency note

Every BigQuery write uses `MERGE` on `video_id`, not `INSERT`. This means
the workflow can be safely re-run multiple times for the same Sunday —
existing rows just get their `views` and `snapshot_taken_at` refreshed;
nothing is ever duplicated. Safe to use `workflow_dispatch` freely for
testing without worrying about polluting the data.

## Known edge cases already handled

- **Scheduled-but-not-yet-public videos:** filtered via
  `status.publishAt` (present only on genuinely future-scheduled
  videos). Deliberately *not* filtered by `privacyStatus`, since PCC's
  actual service livestreams are routinely `unlisted`/`private` by
  design — an earlier attempt at this fix broke livestream detection
  entirely by filtering on `privacyStatus == 'public'` alone.

## Known edge case NOT yet handled

- **Two genuinely public sermon-clip uploads on the same real Sunday**
  (as opposed to one being merely scheduled for later) would still
  cause `SermonVideoId` in Power BI to resolve to blank, since
  `SELECTEDVALUE()` can't disambiguate. A fix was scoped (adding a
  `published_at_full` timestamp column + a DAX `TOPN`-by-earliest
  tiebreak) but deliberately paused pending a check with the YouTube
  team on how common this scenario actually is. Revisit if it recurs.
