import io
import json
import os
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone

import requests

try:
    from collect import (
        ApiRequestError,
        DATA_DIR,
        HISTORY_PATH,
        LIVE_PATH,
        deduplicate,
        fetch_search,
        load_history,
        load_json,
        parse_stat,
        safe_write,
    )
except ModuleNotFoundError:
    from scripts.collect import (
        ApiRequestError,
        DATA_DIR,
        HISTORY_PATH,
        LIVE_PATH,
        deduplicate,
        fetch_search,
        load_history,
        load_json,
        parse_stat,
        safe_write,
    )


TRENDS_INDEX_URL = "https://data.jobtechdev.se/annonser/search-trends/index.html"
TRENDS_FILE_URL = "https://data.jobtechdev.se/annonser/search-trends/{filename}"
TIMEOUT = (20, 120)
DEMAND_GAP_PATH = os.path.join(DATA_DIR, "demand_gap.json")
FILE_PATTERN = re.compile(r"jobsearch-daily-(\d{4}-\d{2}-\d{2})\.zip")


def list_trend_files():
    try:
        response = requests.get(TRENDS_INDEX_URL, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ApiRequestError(str(exc)) from None

    if response.status_code != 200:
        raise ApiRequestError(
            f"API error: HTTP {response.status_code} for {response.url}"
        )

    files = {}
    for match in FILE_PATTERN.finditer(response.text):
        day = date.fromisoformat(match.group(1))
        files[day] = match.group(0)

    if not files:
        raise ApiRequestError("Could not find any search trends files.")

    return files


def load_trend_payload(filename):
    url = TRENDS_FILE_URL.format(filename=filename)
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ApiRequestError(str(exc)) from None

    if response.status_code != 200:
        raise ApiRequestError(f"API error: HTTP {response.status_code} for {response.url}")

    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            members = [name for name in archive.namelist() if name.endswith(".json")]
            if not members:
                raise ApiRequestError(f"Trend archive {filename} did not contain a JSON file.")
            return json.loads(archive.read(members[0]).decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None


def extract_stat_map(payload, key):
    values = payload.get(key, [])
    counts = {}
    if not isinstance(values, list):
        return counts
    for item in values:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
        ):
            continue
        try:
            counts[item[0]] = counts.get(item[0], 0) + int(item[1])
        except (TypeError, ValueError):
            continue
    return counts


def load_live_snapshot():
    snapshot = load_json(LIVE_PATH, {})
    if not isinstance(snapshot, dict) or not snapshot.get("week"):
        raise ApiRequestError(
            "Live snapshot is missing or invalid. Run scripts/collect.py first."
        )
    return snapshot


def build_previous_maps(history):
    if len(history) < 2:
        return {}, {}

    previous_snapshot = history[-2]
    previous_ads = {
        entry["concept_id"]: int(entry["count"])
        for entry in previous_snapshot.get("by_occupation_group", [])
        if isinstance(entry, dict) and entry.get("concept_id")
    }
    return previous_snapshot, previous_ads


def main():
    try:
        live_snapshot = load_live_snapshot()
        history = load_history(HISTORY_PATH)
        trend_files = list_trend_files()
        latest_trend_date = max(trend_files)
        target_previous_date = latest_trend_date - timedelta(days=7)
        previous_trend_date = max(
            (day for day in trend_files if day <= target_previous_date),
            default=None,
        )
        latest_trends = load_trend_payload(trend_files[latest_trend_date])
        previous_trends = (
            load_trend_payload(trend_files[previous_trend_date])
            if previous_trend_date
            else {}
        )

        current_ads_response = fetch_search(
            [
                ("limit", 0),
                ("stats", "occupation-group"),
                ("stats.limit", 30),
            ]
        )
        current_ads_entries = deduplicate(
            parse_stat(current_ads_response.get("stats", []), "occupation-group")
        )
    except ApiRequestError as exc:
        print(exc)
        return 1

    latest_search_counts = extract_stat_map(latest_trends, "occupation-group")
    previous_search_counts = extract_stat_map(previous_trends, "occupation-group")
    _, previous_ad_counts = build_previous_maps(history)

    occupations = []
    changes = []
    for entry in current_ads_entries:
        concept_id = entry.get("concept_id")
        ad_count = int(entry.get("count", 0))
        search_count = int(latest_search_counts.get(concept_id, 0))
        if not concept_id or ad_count <= 0 or search_count <= 0:
            continue

        gap_ratio = round(ad_count / search_count, 2)
        signal = "balanced"
        if gap_ratio > 2:
            signal = "high_demand_low_attention"
        elif gap_ratio < 0.5:
            signal = "high_attention_low_demand"

        occupation = {
            "concept_id": concept_id,
            "term": entry.get("term", concept_id),
            "ad_count": ad_count,
            "search_count": search_count,
            "gap_ratio": gap_ratio,
            "signal": signal,
        }

        previous_search = int(previous_search_counts.get(concept_id, 0))
        previous_ads = int(previous_ad_counts.get(concept_id, 0))
        if previous_search > 0 and previous_ads > 0:
            previous_gap_ratio = round(previous_ads / previous_search, 2)
            occupation["previous_gap_ratio"] = previous_gap_ratio
            changes.append(
                {
                    "term": occupation["term"],
                    "change": round(gap_ratio - previous_gap_ratio, 2),
                }
            )

        occupations.append(occupation)

    occupations.sort(key=lambda item: item["gap_ratio"], reverse=True)
    changes.sort(key=lambda item: abs(item["change"]), reverse=True)

    payload = {
        "week": live_snapshot["week"],
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "occupations": occupations,
        "changes_vs_last_week": changes[:3],
        "trends_file": trend_files[latest_trend_date],
    }

    try:
        safe_write(DEMAND_GAP_PATH, payload)
    except OSError as exc:
        print(exc)
        return 1

    print(
        f"Wrote {DEMAND_GAP_PATH} for {payload['week']} with "
        f"{len(payload['occupations'])} occupation groups."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
