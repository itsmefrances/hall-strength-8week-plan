# Hall Strength — 8-Week Block 1

Training plan site for weeks 14–21 (strength + aerobic power), published via GitHub Pages from `index.html`.

## Concept2 logbook sync

Erg sessions on the site are automatically marked **✓ Completed** — with distance, time, pace, stroke rate, HR, and a link to the logbook entry — by pulling results from the [Concept2 Logbook API](https://log.concept2.com/developers/documentation/).

How it works:

- `.github/workflows/sync-concept2.yml` runs every 6 hours (and on demand from the Actions tab).
- `scripts/sync_concept2.py` fetches all logbook results in the plan's date range and matches each one to a prescribed erg slot **anywhere within the same plan week** — doing a session on a different day than prescribed is fine.
- Matched results are written to `data/results.json`, which `index.html` reads and overlays on the plan.

### Matching rules (best first)

1. **Name tag** — if the workout comments contain e.g. `W14 S1` (or `Hall Strength Erg W15 S3`), it is pinned to that exact slot, even if rowed in a different calendar week. *Tip: putting the session name in the ErgData workout comment makes matching exact.*
2. **Session-type words** — "sprint", "zone 2" / "z2" in comments.
3. **Workout shape** — many short intervals → Custom Sprint; a few structured intervals → S3; continuous ≥28 min at/under HR 145 → Zone 2; continuous 15–50 min → S1/S5.
4. **Closest day** — remaining rower workouts ≥10 min fill remaining S1/S5 slots, preferring the prescribed day. These show an "auto-matched" note on the site.

Anything that can't be matched is kept under `unmatched` in `data/results.json` for inspection.

### One-time setup

1. **Get Concept2 API credentials**: request an API key at <https://log.concept2.com/developers/keys> with redirect URI exactly `http://localhost:8676/callback`. You'll receive a client ID and client secret.
2. **Authorize once** (on your own computer):
   ```
   python3 scripts/concept2_auth.py YOUR_CLIENT_ID YOUR_CLIENT_SECRET
   ```
   Log in to Concept2 in the browser tab that opens; the script prints your refresh token.
3. **Add repository secrets** (GitHub → Settings → Secrets and variables → Actions):
   - `C2_CLIENT_ID`
   - `C2_CLIENT_SECRET`
   - `C2_REFRESH_TOKEN`
   - `ACTIONS_PAT` *(recommended)* — a [fine-grained personal access token](https://github.com/settings/personal-access-tokens) scoped to this repo with **Secrets: read & write**. Concept2 issues a new refresh token on each sync; this lets the workflow store it. Without it, the sync may stop working after the first run and you'd need to re-run step 2.
4. **Run it**: Actions tab → "Sync Concept2 results" → Run workflow. After it completes, the site shows your logged workouts.

### Configuration

`scripts/sync_config.json`:

- `week_14_monday` — the Monday of plan Week 14 (currently `2026-06-08`). **Adjust this if the block starts a different week** — all matching is anchored to it.
- `zone2_hr_ceiling`, `min_fallback_minutes` — matching thresholds.
- `slots` / `week_slot_overrides` — the prescribed erg sessions per week.
