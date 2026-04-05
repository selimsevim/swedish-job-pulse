import argparse
import bisect
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import requests

try:
    from collect import (
        ApiRequestError,
        HISTORY_PATH,
        META_PATH,
        build_meta,
        load_history,
        safe_write,
    )
except ModuleNotFoundError:
    from scripts.collect import (
        ApiRequestError,
        HISTORY_PATH,
        META_PATH,
        build_meta,
        load_history,
        safe_write,
    )


# Weekly history for the dashboard should approximate point-in-time market
# snapshots rather than weekly publication volume. The historical ads docs note
# that the API is best suited for trends rather than exact statistics, so this
# backfill keeps requests practical by reconstructing snapshots from a bounded
# publication window instead of scanning full yearly archives. Ads published
# before the carryover buffer may still be missed if they remained active for a
# very long time, but the resulting trend line is much more practical to build.
LIVE_SEARCH_URL = "https://jobsearch.api.jobtechdev.se/search"
HISTORICAL_SEARCH_URL = "https://historical.api.jobtechdev.se/search"
TIMEOUT = 20
PAGE_SIZE = 100
MAX_OFFSET = 2000
CARRYOVER_DAYS = 120
MAX_WORKERS = 4
WINDOW_HOURS = 24
SNAPSHOT_HIT_FIELDS = (
    "total{value},hits{"
    "id,original_id,external_id,publication_date,last_publication_date,removed_date,"
    "number_of_vacancies,"
    "occupation_field{concept_id,term,label},"
    "occupation_group{concept_id,term,label},"
    "workplace_address{municipality,municipality_concept_id,region,region_concept_id}"
    "}"
)
REMOTE_HIT_FIELDS = (
    "total{value},hits{"
    "id,original_id,external_id,publication_date,last_publication_date,removed_date"
    "}"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill weekly Swedish Job Pulse snapshot history."
    )
    parser.add_argument("weeks", nargs="?", type=int, default=52)
    return parser.parse_args()


def parse_date_string(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def record_key(record):
    if not isinstance(record, dict):
        return None
    return record.get("original_id") or record.get("id") or record.get("external_id")


def normalize_vacancies(value):
    try:
        vacancies = int(value)
    except (TypeError, ValueError):
        return 1
    return vacancies if vacancies > 0 else 1


def normalize_taxonomy_entries(value):
    if isinstance(value, dict):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []

    entries = []
    seen = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        concept_id = item.get("concept_id")
        term = item.get("term") or item.get("label")
        if not concept_id or not term or concept_id in seen:
            continue
        seen.add(concept_id)
        entries.append((concept_id, term))
    return entries


def extract_region_entry(record):
    workplace = record.get("workplace_address")
    if not isinstance(workplace, dict):
        return []

    concept_id = workplace.get("region_concept_id")
    term = workplace.get("region")
    if concept_id and term:
        return [(concept_id, term)]
    return []


def extract_municipality_entry(record):
    workplace = record.get("workplace_address")
    if not isinstance(workplace, dict):
        return []

    concept_id = workplace.get("municipality_concept_id")
    term = workplace.get("municipality")
    if concept_id and term:
        return [(concept_id, term)]
    return []


def get_active_date_range(record):
    publication_date = parse_date_string(record.get("publication_date"))
    if publication_date is None:
        return None, None

    end_candidates = [
        parse_date_string(record.get("last_publication_date")),
        parse_date_string(record.get("removed_date")),
    ]
    end_candidates = [candidate for candidate in end_candidates if candidate is not None]
    end_date = min(end_candidates) if end_candidates else publication_date
    return publication_date, end_date


def make_snapshot_state(snapshot_date):
    return {
        "date": snapshot_date,
        "total_ads": 0,
        "total_positions": 0,
        "remote_ads": 0,
        "occupation_field_counts": defaultdict(int),
        "occupation_field_terms": {},
        "occupation_group_counts": defaultdict(int),
        "occupation_group_terms": {},
        "region_counts": defaultdict(int),
        "region_terms": {},
        "municipality_counts": defaultdict(int),
        "municipality_terms": {},
    }


def update_count(counts, terms, entries):
    for concept_id, term in entries:
        counts[concept_id] += 1
        terms.setdefault(concept_id, term)


def build_sorted_entries(counts, terms):
    return [
        {
            "concept_id": concept_id,
            "term": terms[concept_id],
            "count": count,
        }
        for concept_id, count in sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]


def snapshot_from_state(state):
    snapshot_date = state["date"]
    return {
        "week": snapshot_date.strftime("%G-W%V"),
        "date": snapshot_date.isoformat(),
        "total_ads": state["total_ads"],
        "total_positions": state["total_positions"],
        "remote_ads": state["remote_ads"],
        "by_occupation_field": build_sorted_entries(
            state["occupation_field_counts"],
            state["occupation_field_terms"],
        ),
        "by_occupation_group": build_sorted_entries(
            state["occupation_group_counts"],
            state["occupation_group_terms"],
        ),
        "by_region": build_sorted_entries(
            state["region_counts"],
            state["region_terms"],
        ),
        "by_municipality": build_sorted_entries(
            state["municipality_counts"],
            state["municipality_terms"],
        ),
    }


def process_record(record, target_dates, states, remote_only=False):
    publication_date, end_date = get_active_date_range(record)
    if publication_date is None or end_date is None:
        return

    start_index = bisect.bisect_left(target_dates, publication_date)
    end_index = bisect.bisect_right(target_dates, end_date) - 1
    if start_index > end_index:
        return

    if remote_only:
        for snapshot_date in target_dates[start_index : end_index + 1]:
            states[snapshot_date]["remote_ads"] += 1
        return

    vacancies = normalize_vacancies(record.get("number_of_vacancies"))
    occupation_fields = normalize_taxonomy_entries(record.get("occupation_field"))
    occupation_groups = normalize_taxonomy_entries(record.get("occupation_group"))
    regions = extract_region_entry(record)
    municipalities = extract_municipality_entry(record)

    for snapshot_date in target_dates[start_index : end_index + 1]:
        state = states[snapshot_date]
        state["total_ads"] += 1
        state["total_positions"] += vacancies
        update_count(
            state["occupation_field_counts"],
            state["occupation_field_terms"],
            occupation_fields,
        )
        update_count(
            state["occupation_group_counts"],
            state["occupation_group_terms"],
            occupation_groups,
        )
        update_count(
            state["region_counts"],
            state["region_terms"],
            regions,
        )
        update_count(
            state["municipality_counts"],
            state["municipality_terms"],
            municipalities,
        )


def fetch_json(url, params, headers=None):
    try:
        response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ApiRequestError(str(exc)) from None

    if response.status_code != 200:
        raise ApiRequestError(f"API error: HTTP {response.status_code} for {response.url}")

    try:
        return response.json()
    except ValueError as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None


def format_api_datetime(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def split_api_window(start_dt, end_dt):
    midpoint = start_dt + ((end_dt - start_dt) / 2)
    midpoint = midpoint.replace(microsecond=0)

    if midpoint <= start_dt:
        midpoint = start_dt + timedelta(seconds=1)

    right_start = midpoint + timedelta(seconds=1)
    if midpoint >= end_dt or right_start > end_dt:
        return None

    return (start_dt, midpoint), (right_start, end_dt)


def build_api_windows(start_dt, end_dt):
    windows = []
    current_start = start_dt

    while current_start <= end_dt:
        current_end = min(
            current_start + timedelta(hours=WINDOW_HOURS) - timedelta(seconds=1),
            end_dt,
        )
        windows.append((current_start, current_end))
        current_start = current_end + timedelta(seconds=1)

    return windows


def fetch_window_hits(url, extra_params, start_dt, end_dt, fields):
    offset = 0
    seen = set()
    hits_for_window = []

    while True:
        params = [
            ("limit", PAGE_SIZE),
            ("offset", offset),
            ("sort", "pubdate-asc"),
            ("published-after", format_api_datetime(start_dt)),
            ("published-before", format_api_datetime(end_dt)),
        ]
        params.extend(extra_params)
        payload = fetch_json(url, params, headers={"X-Fields": fields})

        try:
            hits = payload["hits"]
        except KeyError as exc:
            raise ApiRequestError(f"Unexpected response shape: {exc}") from None

        if not isinstance(hits, list):
            raise ApiRequestError("Unexpected response shape: hits is not a list")

        if not hits:
            break

        for hit in hits:
            key = record_key(hit)
            if key is None or key in seen:
                continue
            seen.add(key)
            hits_for_window.append(hit)

        if len(hits) < PAGE_SIZE:
            break

        offset += len(hits)
        if offset > MAX_OFFSET:
            split_windows = split_api_window(start_dt, end_dt)
            if split_windows is None:
                raise ApiRequestError(
                    "API window is too dense to page safely. "
                    f"Window: {format_api_datetime(start_dt)} to {format_api_datetime(end_dt)}"
                )

            left_hits = fetch_window_hits(
                url,
                extra_params,
                split_windows[0][0],
                split_windows[0][1],
                fields,
            )
            right_hits = fetch_window_hits(
                url,
                extra_params,
                split_windows[1][0],
                split_windows[1][1],
                fields,
            )
            return left_hits + right_hits

    return hits_for_window


def target_dates_to_backfill(weeks, history):
    if weeks <= 0:
        return []

    history_dates = sorted(
        parse_date_string(entry.get("date"))
        for entry in history
        if isinstance(entry, dict)
    )
    history_dates = [entry for entry in history_dates if entry is not None]

    anchor_date = history_dates[0] if history_dates else date.today()
    return sorted(anchor_date - timedelta(days=7 * offset) for offset in range(1, weeks + 1))


def publication_window_for_targets(target_dates):
    earliest_target = target_dates[0]
    latest_target = target_dates[-1]
    window_start = earliest_target - timedelta(days=CARRYOVER_DAYS)
    return (
        datetime(window_start.year, window_start.month, window_start.day, 0, 0, 0),
        datetime(latest_target.year, latest_target.month, latest_target.day, 23, 59, 59),
    )


def process_source(url, target_dates, states, extra_params, label, seen):
    window_start, window_end = publication_window_for_targets(target_dates)
    fields = REMOTE_HIT_FIELDS if extra_params else SNAPSHOT_HIT_FIELDS
    windows = build_api_windows(window_start, window_end)
    print(
        f"{label}: {window_start.date().isoformat()} to {window_end.date().isoformat()} "
        f"across {len(windows)} windows"
    )

    if not windows:
        return

    processed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {
            executor.submit(
                fetch_window_hits,
                url,
                extra_params,
                start_dt,
                end_dt,
                fields,
            ): (start_dt, end_dt)
            for start_dt, end_dt in windows
        }

        for future in as_completed(future_map):
            records = future.result()
            for record in records:
                key = record_key(record)
                if key is None or key in seen:
                    continue
                seen.add(key)
                process_record(record, target_dates, states, remote_only=bool(extra_params))

            processed += 1
            if processed == len(windows) or processed % 10 == 0:
                print(f"  {processed}/{len(windows)} windows complete")


def week_label(snapshot):
    week_value = snapshot["week"]
    if "-" in week_value:
        return week_value.split("-", 1)[1]
    return week_value


def main():
    args = parse_args()
    weeks = max(args.weeks, 0)

    history = load_history(HISTORY_PATH)
    known_weeks = {
        entry.get("week")
        for entry in history
        if isinstance(entry, dict) and entry.get("week")
    }

    candidate_dates = target_dates_to_backfill(weeks, history)
    target_dates = [
        snapshot_date
        for snapshot_date in candidate_dates
        if snapshot_date.strftime("%G-W%V") not in known_weeks
    ]

    if not target_dates:
        print("No missing weekly snapshots to backfill.")
        return 0

    print(
        "Using API-based trend reconstruction with a "
        f"{CARRYOVER_DAYS}-day carryover buffer."
    )

    states = {snapshot_date: make_snapshot_state(snapshot_date) for snapshot_date in target_dates}
    seen_all = set()
    seen_remote = set()

    try:
        process_source(
            HISTORICAL_SEARCH_URL,
            target_dates,
            states,
            [],
            "Fetching unpublished ads from historical API",
            seen_all,
        )
        process_source(
            LIVE_SEARCH_URL,
            target_dates,
            states,
            [],
            "Fetching still-active ads from live API",
            seen_all,
        )
        process_source(
            HISTORICAL_SEARCH_URL,
            target_dates,
            states,
            [("remote", "true")],
            "Fetching unpublished remote ads from historical API",
            seen_remote,
        )
        process_source(
            LIVE_SEARCH_URL,
            target_dates,
            states,
            [("remote", "true")],
            "Fetching still-active remote ads from live API",
            seen_remote,
        )
    except ApiRequestError as exc:
        print(exc)
        return 1

    snapshots = [snapshot_from_state(states[snapshot_date]) for snapshot_date in target_dates]
    for snapshot in snapshots:
        history.append(snapshot)
        print(f"Backfilled {week_label(snapshot)}: {snapshot['total_ads']:,} ads.")

    history.sort(key=lambda item: item.get("date", "") if isinstance(item, dict) else "")
    latest_date = history[-1]["date"] if history else None
    meta = build_meta(history, latest_date)

    try:
        safe_write(HISTORY_PATH, history)
        safe_write(META_PATH, meta)
    except OSError as exc:
        print(exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
