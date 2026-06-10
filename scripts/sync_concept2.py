#!/usr/bin/env python3
"""Sync Concept2 Logbook results into data/results.json for the training plan site.

Fetches all logbook results in the plan's date range, matches each one to a
prescribed erg slot in the matching plan week, and writes data/results.json,
which index.html reads to mark sessions complete.

Matching strategy, in priority order:
  1. Explicit name tag in the result comments, e.g. "W14 S1" or "Hall Strength
     Erg W15 S3" (the week tag in the name wins over the calendar week).
  2. Session-type tags in comments: "zone 2" / "z2", "sprint", "S1"/"S3"/"S5".
  3. Workout-shape heuristics within the calendar week:
       - Custom Sprint: many short intervals (10 x 5 max strokes)
       - Zone 2: continuous piece >= 28 min at/below the HR ceiling
       - S3: a handful of structured intervals (2K-pace work)
  4. Fallback: any remaining rower workout >= min_fallback_minutes fills the
     remaining open S1/S5 slots, preferring the one closest to its prescribed
     day. (The plan allows doing a session on a different day in the week.)

Environment variables (required):
  C2_CLIENT_ID, C2_CLIENT_SECRET, C2_REFRESH_TOKEN

If Concept2 rotates the refresh token, the new one is written to
.c2_new_refresh_token so the CI workflow can update the repo secret.

Stdlib only — no dependencies.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = "https://log.concept2.com"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, "scripts", "sync_config.json")
OUTPUT_PATH = os.path.join(REPO_ROOT, "data", "results.json")
NEW_TOKEN_PATH = os.path.join(REPO_ROOT, ".c2_new_refresh_token")

NAME_WEEK_SLOT_RE = re.compile(r"\bW\s*(\d{1,2})\s*[-– ]*S\s*([135])\b", re.IGNORECASE)
NAME_SLOT_RE = re.compile(r"\bS\s*([135])\b", re.IGNORECASE)


def http_json(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code} from {url}: {body[:500]}")


def refresh_access_token(client_id, client_secret, refresh_token):
    payload = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "user:read,results:read",
    }).encode("utf-8")
    tok = http_json(
        f"{BASE}/oauth/access_token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    new_refresh = tok.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        with open(NEW_TOKEN_PATH, "w") as f:
            f.write(new_refresh)
        print("Refresh token rotated; wrote .c2_new_refresh_token")
    return tok["access_token"]


def fetch_results(access_token, date_from, date_to):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.c2logbook.v1+json",
    }
    results, page = [], 1
    while True:
        qs = urllib.parse.urlencode({"from": date_from, "to": date_to, "page": page})
        body = http_json(f"{BASE}/api/users/me/results?{qs}", headers=headers)
        results.extend(body.get("data", []))
        pagination = (body.get("meta") or {}).get("pagination") or {}
        total_pages = pagination.get("total_pages", 1)
        if page >= total_pages:
            return results
        page += 1


def parse_result_date(r):
    raw = r.get("date") or ""
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()


def fmt_time(tenths):
    if not tenths:
        return None
    seconds = tenths / 10.0
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{int(m)}:{s:04.1f}"


def fmt_pace(time_tenths, distance):
    if not time_tenths or not distance:
        return None
    return fmt_time(time_tenths / distance * 500)


def intervals_of(r):
    workout = r.get("workout") or {}
    iv = workout.get("intervals")
    return iv if isinstance(iv, list) else []


def avg_hr(r):
    hr = r.get("heart_rate")
    if isinstance(hr, dict):
        return hr.get("average")
    return None


def text_of(r):
    parts = [str(r.get("comments") or "")]
    workout = r.get("workout") or {}
    for key in ("name", "title"):
        if workout.get(key):
            parts.append(str(workout[key]))
    return " ".join(parts)


def duration_minutes(r):
    return (r.get("time") or 0) / 600.0


def classify(r, cfg):
    """Return {kind: score} heuristic classification of a result."""
    scores = {}
    text = text_of(r).lower()
    n_iv = len(intervals_of(r))
    mins = duration_minutes(r)

    if re.search(r"\bsprint\b", text):
        scores["sprint"] = 60
    if re.search(r"\b(zone\s*2|z2|steady)\b", text):
        scores["z2"] = 60

    if n_iv >= 6:
        iv_times = [iv.get("time") or 0 for iv in intervals_of(r)]
        if iv_times and max(iv_times) <= 600:  # every interval <= 60s of work
            scores["sprint"] = max(scores.get("sprint", 0), 45)
        else:
            scores["s3"] = max(scores.get("s3", 0), 30)
    elif 2 <= n_iv <= 8:
        scores["s3"] = max(scores.get("s3", 0), 35)
    elif n_iv == 0 and mins >= 28:
        hr = avg_hr(r)
        if hr is None or hr <= cfg["zone2_hr_ceiling"]:
            scores["z2"] = max(scores.get("z2", 0), 40)

    # A medium continuous piece could also be S1/S5; with the day-proximity
    # bonus, a piece rowed on its prescribed day wins over a distant Z2 slot.
    if n_iv == 0 and 15 <= mins <= 50:
        scores.setdefault("s1", 35)
        scores.setdefault("s5", 35)

    return scores


def build_match_payload(r, matched_by):
    time_tenths = r.get("time")
    distance = r.get("distance")
    return {
        "id": r.get("id"),
        "date": r.get("date"),
        "machine": r.get("type"),
        "distance_m": distance,
        "time_display": fmt_time(time_tenths),
        "pace_per_500m": fmt_pace(time_tenths, distance),
        "stroke_rate": r.get("stroke_rate"),
        "avg_hr": avg_hr(r),
        "workout_type": r.get("workout_type"),
        "comments": r.get("comments"),
        "matched_by": matched_by,
        "logbook_url": f"{BASE}/profile/{r.get('user_id')}/log/{r.get('id')}",
    }


def week_slots(week, cfg):
    override = cfg.get("week_slot_overrides", {}).get(str(week))
    names = override if override else list(cfg["slots"].keys())
    return {name: cfg["slots"][name] for name in names}


def match_week(week, results, cfg):
    """Greedily assign this week's results to this week's open slots."""
    slots = week_slots(week, cfg)
    matches, used_results, used_slots = {}, set(), set()

    def take(idx, slot_name, how):
        matches[f"W{week}-{slot_name}"] = build_match_payload(results[idx], how)
        used_results.add(idx)
        used_slots.add(slot_name)

    # Pass 1: explicit "W<week> S<n>" / "S<n>" name tags in comments.
    for idx, r in enumerate(results):
        text = text_of(r)
        m = NAME_WEEK_SLOT_RE.search(text) or NAME_SLOT_RE.search(text)
        if not m:
            continue
        slot_name = f"S{m.group(m.lastindex)}"
        if slot_name in slots and slot_name not in used_slots:
            take(idx, slot_name, "name")

    # Pass 2: heuristic classification (sprint / zone 2 / S3 intervals),
    # scored with a same-week day-proximity bonus, assigned best-first.
    candidates = []
    for idx, r in enumerate(results):
        if idx in used_results:
            continue
        kind_scores = classify(r, cfg)
        result_day = parse_result_date(r).weekday()
        for slot_name, slot in slots.items():
            if slot_name in used_slots or slot["kind"] not in kind_scores:
                continue
            if slot["kind"] != "z2" and r.get("type") not in (None, "rower", "slides", "dynamic"):
                continue
            day_bonus = 10 if result_day == slot["day"] else max(0, 8 - 2 * abs(result_day - slot["day"]))
            candidates.append((kind_scores[slot["kind"]] + day_bonus, idx, slot_name))
    for score, idx, slot_name in sorted(candidates, reverse=True):
        if idx not in used_results and slot_name not in used_slots:
            take(idx, slot_name, "heuristic")

    # Pass 3: remaining rower workouts fill remaining S1/S5 slots by day proximity.
    fallback = []
    for idx, r in enumerate(results):
        if idx in used_results or r.get("type") not in (None, "rower", "slides", "dynamic"):
            continue
        if duration_minutes(r) < cfg["min_fallback_minutes"]:
            continue
        result_day = parse_result_date(r).weekday()
        for slot_name, slot in slots.items():
            if slot_name in used_slots or slot["kind"] not in ("s1", "s5"):
                continue
            fallback.append((-abs(result_day - slot["day"]), idx, slot_name))
    for _, idx, slot_name in sorted(fallback, reverse=True):
        if idx not in used_results and slot_name not in used_slots:
            take(idx, slot_name, "closest-day")

    unmatched = [build_match_payload(r, None) for idx, r in enumerate(results) if idx not in used_results]
    return matches, unmatched


def main():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)

    client_id = os.environ.get("C2_CLIENT_ID")
    client_secret = os.environ.get("C2_CLIENT_SECRET")
    refresh_token = os.environ.get("C2_REFRESH_TOKEN")
    if not all([client_id, client_secret, refresh_token]):
        raise SystemExit(
            "Missing C2_CLIENT_ID / C2_CLIENT_SECRET / C2_REFRESH_TOKEN environment variables.\n"
            "Run scripts/concept2_auth.py once to obtain a refresh token (see README)."
        )

    week14 = date.fromisoformat(cfg["week_14_monday"])
    first_week, last_week = cfg["first_week"], cfg["last_week"]
    range_from = week14.isoformat()
    range_to = (week14 + timedelta(days=7 * (last_week - first_week + 1) - 1)).isoformat()

    access_token = refresh_access_token(client_id, client_secret, refresh_token)
    results = fetch_results(access_token, range_from, range_to)
    print(f"Fetched {len(results)} results between {range_from} and {range_to}")

    by_week = {}
    for r in results:
        # A "W15 S1" style name tag pins the result to that plan week even if
        # it was rowed in a different calendar week.
        tag = NAME_WEEK_SLOT_RE.search(text_of(r))
        if tag and first_week <= int(tag.group(1)) <= last_week:
            week = int(tag.group(1))
        else:
            week = first_week + (parse_result_date(r) - week14).days // 7
        if first_week <= week <= last_week:
            by_week.setdefault(week, []).append(r)

    all_matches, all_unmatched = {}, {}
    for week, week_results in sorted(by_week.items()):
        matches, unmatched = match_week(week, week_results, cfg)
        all_matches.update(matches)
        if unmatched:
            all_unmatched[str(week)] = unmatched

    output = {
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week_14_monday": cfg["week_14_monday"],
        "matches": all_matches,
        "unmatched": all_unmatched,
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    print(f"Matched {len(all_matches)} sessions; wrote {os.path.relpath(OUTPUT_PATH, REPO_ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
