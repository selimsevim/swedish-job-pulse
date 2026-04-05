import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone

import requests


BASE_URL = "https://jobsearch.api.jobtechdev.se/search"
TIMEOUT = 20
REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")
LIVE_PATH = os.path.join(DATA_DIR, "live.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
META_PATH = os.path.join(DATA_DIR, "meta.json")
STAT_TYPES = (
    "occupation-field",
    "occupation-group",
    "region",
    "municipality",
)


class ApiRequestError(Exception):
    pass


def default_meta():
    return {
        "last_updated": None,
        "weeks_tracked": 0,
        "date_range": {
            "from": None,
            "to": None,
        },
    }


def safe_write(path, data):
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_path,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def load_json(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading {path}: {exc}")
        return default


def load_history(path):
    history = load_json(path, [])
    if isinstance(history, list):
        return history

    print(f"Error reading {path}: expected a JSON array.")
    return []


def load_meta(path):
    meta = load_json(path, default_meta())
    if isinstance(meta, dict):
        return meta

    print(f"Error reading {path}: expected a JSON object.")
    return default_meta()


def fetch_search(params):
    try:
        response = requests.get(BASE_URL, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ApiRequestError(str(exc)) from None

    if response.status_code != 200:
        raise ApiRequestError(f"API error: HTTP {response.status_code} for {response.url}")

    try:
        return response.json()
    except ValueError as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None


def resolve_positions_count(all_ads_payload, extra_params=None):
    try:
        total_ads = int(all_ads_payload["total"]["value"])
        positions = int(all_ads_payload["positions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None

    if positions != 0 or total_ads == 0:
        return positions

    # The aggregate stats query currently reports 0 positions for limit=0,
    # so fetch a single hit to get the correct total position count.
    params = [("limit", 1)]
    if extra_params:
        params.extend(extra_params)

    positions_payload = fetch_search(params)
    try:
        return int(positions_payload["positions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None


def parse_stat(stats_array, stat_type):
    for entry in stats_array:
        if entry["type"] == stat_type:
            return [
                {
                    "concept_id": value["concept_id"],
                    "term": value["term"],
                    "count": value["count"],
                }
                for value in entry["values"]
            ]
    return []


def deduplicate(entries):
    merged = {}

    for entry in entries:
        concept_id = entry["concept_id"]
        if concept_id in merged:
            merged[concept_id]["count"] += entry["count"]
        else:
            merged[concept_id] = {
                "concept_id": concept_id,
                "term": entry["term"],
                "count": entry["count"],
            }

    return sorted(merged.values(), key=lambda item: item["count"], reverse=True)


def build_snapshot(
    all_ads_payload,
    remote_payload,
    snapshot_date,
    total_positions,
    remote_by_field,
    entry_level_ads,
    entry_by_field,
    trainee_ads,
    larling_ads,
):
    try:
        stats_array = all_ads_payload["stats"]
        total_ads = int(all_ads_payload["total"]["value"])
        remote_ads = int(remote_payload["total"]["value"])
        occupation_field = deduplicate(parse_stat(stats_array, "occupation-field"))
        occupation_group = deduplicate(parse_stat(stats_array, "occupation-group"))
        regions = deduplicate(parse_stat(stats_array, "region"))
        municipalities = deduplicate(parse_stat(stats_array, "municipality"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None

    return {
        "week": snapshot_date.strftime("%G-W%V"),
        "date": snapshot_date.isoformat(),
        "total_ads": total_ads,
        "total_positions": total_positions,
        "remote_ads": remote_ads,
        "remote_by_field": remote_by_field,
        "entry_level_ads": entry_level_ads,
        "entry_by_field": entry_by_field,
        "trainee_ads": trainee_ads,
        "larling_ads": larling_ads,
        "by_occupation_field": occupation_field,
        "by_occupation_group": occupation_group,
        "by_region": regions,
        "by_municipality": municipalities,
    }


def build_meta(history, latest_date):
    return {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weeks_tracked": len(history),
        "date_range": {
            "from": history[0]["date"] if history else None,
            "to": latest_date if history else None,
        },
    }


def main():
    today = date.today()
    all_ads_params = [
        ("limit", 0),
        ("stats", "occupation-field"),
        ("stats", "occupation-group"),
        ("stats", "region"),
        ("stats", "municipality"),
    ]
    remote_params = [
        ("limit", 0),
        ("remote", "true"),
    ]
    remote_field_params = [
        ("limit", "0"),
        ("remote", "true"),
        ("stats", "occupation-field"),
    ]
    entry_params = [
        ("limit", "0"),
        ("experience", "false"),
    ]
    entry_field_params = [
        ("limit", "0"),
        ("experience", "false"),
        ("stats", "occupation-field"),
    ]
    trainee_params = [
        ("limit", "0"),
        ("trainee", "true"),
    ]
    larling_params = [
        ("limit", "0"),
        ("larling", "true"),
    ]

    try:
        all_ads_payload = fetch_search(all_ads_params)
        remote_payload = fetch_search(remote_params)
        remote_field_response = fetch_search(remote_field_params)
        remote_by_field = deduplicate(parse_stat(
            remote_field_response.get("stats", []), "occupation-field"
        ))
        entry_response = fetch_search(entry_params)
        entry_level_ads = int(entry_response["total"]["value"])
        entry_field_response = fetch_search(entry_field_params)
        entry_by_field = deduplicate(parse_stat(
            entry_field_response.get("stats", []), "occupation-field"
        ))
        trainee_response = fetch_search(trainee_params)
        trainee_ads = int(trainee_response["total"]["value"])
        larling_response = fetch_search(larling_params)
        larling_ads = int(larling_response["total"]["value"])
        total_positions = resolve_positions_count(all_ads_payload)
        snapshot = build_snapshot(
            all_ads_payload,
            remote_payload,
            today,
            total_positions,
            remote_by_field,
            entry_level_ads,
            entry_by_field,
            trainee_ads,
            larling_ads,
        )
    except (ApiRequestError, KeyError, TypeError, ValueError) as exc:
        if not isinstance(exc, ApiRequestError):
            print(f"Unexpected response shape: {exc}")
            return 1
        print(exc)
        return 1

    history = load_history(HISTORY_PATH)
    load_meta(META_PATH)

    if any(isinstance(entry, dict) and entry.get("week") == snapshot["week"] for entry in history):
        print("Week already collected, skipping.")
        return 0

    history.append(snapshot)
    meta = build_meta(history, snapshot["date"])

    try:
        safe_write(LIVE_PATH, snapshot)
        safe_write(HISTORY_PATH, history)
        safe_write(META_PATH, meta)
    except OSError as exc:
        print(exc)
        return 1

    remote_pct = 0.0
    if snapshot["total_ads"]:
        remote_pct = (snapshot["remote_ads"] / snapshot["total_ads"]) * 100
    entry_pct = 0.0
    if snapshot["total_ads"]:
        entry_pct = (snapshot["entry_level_ads"] / snapshot["total_ads"]) * 100

    print(f"Week {snapshot['week']} collected.")
    print(f"Total ads: {snapshot['total_ads']}")
    print(f"Total positions: {snapshot['total_positions']}")
    print(f"Remote ads: {snapshot['remote_ads']} ({remote_pct:.1f}%)")
    print(f"Entry-level ads: {snapshot['entry_level_ads']} ({entry_pct:.1f}%)")
    print(f"Weeks in history: {len(history)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
