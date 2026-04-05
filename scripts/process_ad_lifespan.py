import argparse
import io
import json
import os
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean, median

import requests

try:
    from collect import (
        ApiRequestError,
        BASE_URL,
        DATA_DIR,
        HISTORY_PATH,
        LIVE_PATH,
        TIMEOUT,
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
        BASE_URL,
        DATA_DIR,
        HISTORY_PATH,
        LIVE_PATH,
        TIMEOUT,
        deduplicate,
        fetch_search,
        load_history,
        load_json,
        parse_stat,
        safe_write,
    )

try:
    from process_decay import ArchiveError, download_archive, get_zip_member_name
except ModuleNotFoundError:
    from scripts.process_decay import ArchiveError, download_archive, get_zip_member_name


DEFAULT_OUTPUT = Path(DATA_DIR) / "ad_lifespan.json"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate data/ad_lifespan.json from archive and live data."
    )
    parser.add_argument("--year", type=int, default=date.today().year - 1)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def parse_date_string(value):
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value[:19]).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def normalize_field(record):
    value = record.get("occupation_field")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return None
    concept_id = value.get("concept_id")
    term = value.get("label") or value.get("term")
    if not concept_id or not term:
        return None
    return concept_id, term


def fetch_live_json(params, headers=None):
    try:
        response = requests.get(
            BASE_URL,
            params=params,
            headers=headers or {},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ApiRequestError(str(exc)) from None

    if response.status_code != 200:
        raise ApiRequestError(f"API error: HTTP {response.status_code} for {response.url}")

    try:
        return response.json()
    except ValueError as exc:
        raise ApiRequestError(f"Unexpected response shape: {exc}") from None


def main():
    args = parse_args()
    archive_path = None
    closed_lifespans = defaultdict(list)
    field_terms = {}
    processed = 0
    matched = 0

    print(f"Downloading and processing lifespan archive for {args.year}...")

    try:
        archive_path = download_archive(args.year)
        with zipfile.ZipFile(archive_path) as archive:
            member_name = get_zip_member_name(archive)
            with archive.open(member_name) as raw_handle:
                with io.TextIOWrapper(raw_handle, encoding="utf-8") as text_handle:
                    for line_number, line in enumerate(text_handle, start=1):
                        row = line.strip()
                        if not row:
                            continue

                        try:
                            record = json.loads(row)
                        except json.JSONDecodeError as exc:
                            raise ArchiveError(
                                f"Unexpected archive content in {args.year} at line {line_number}: {exc}"
                            ) from None

                        processed += 1
                        occupation_field = normalize_field(record)
                        if not occupation_field:
                            continue

                        publication_date = parse_date_string(record.get("publication_date"))
                        end_candidates = [
                            parse_date_string(record.get("removed_date")),
                            parse_date_string(record.get("last_publication_date")),
                        ]
                        end_candidates = [candidate for candidate in end_candidates if candidate]
                        if not publication_date or not end_candidates:
                            continue

                        end_date = min(end_candidates)
                        lifespan_days = (end_date - publication_date).days
                        if lifespan_days < 0:
                            continue

                        concept_id, term = occupation_field
                        closed_lifespans[concept_id].append(lifespan_days)
                        field_terms.setdefault(concept_id, term)
                        matched += 1
    except (ArchiveError, ApiRequestError) as exc:
        print(exc)
        return 1
    finally:
        if archive_path and os.path.exists(archive_path):
            os.remove(archive_path)

    if not matched:
        print("Archive did not contain usable lifespan data.")
        return 1

    live_snapshot = load_json(LIVE_PATH, {})
    history = load_history(HISTORY_PATH)
    if not isinstance(live_snapshot, dict) or not live_snapshot.get("week"):
        print("Live snapshot is missing or invalid. Run scripts/collect.py first.")
        return 1

    try:
        current_fields_response = fetch_search(
            [
                ("limit", 0),
                ("stats", "occupation-field"),
                ("stats.limit", 30),
            ]
        )
        current_field_entries = deduplicate(
            parse_stat(current_fields_response.get("stats", []), "occupation-field")
        )
        oldest_live = fetch_live_json(
            [("limit", 20), ("sort", "pubdate-asc")],
            headers={
                "X-Fields": (
                    "hits{id,headline,publication_date,"
                    "occupation_field{concept_id,label},"
                    "workplace_address{region}}"
                )
            },
        )
    except ApiRequestError as exc:
        print(exc)
        return 1

    occupation_fields = []
    live_fields = {
        entry["concept_id"]: entry
        for entry in current_field_entries
        if isinstance(entry, dict) and entry.get("concept_id")
    }
    for concept_id, live_entry in live_fields.items():
        lifespans = closed_lifespans.get(concept_id, [])
        if not lifespans:
            continue
        occupation_fields.append(
            {
                "term": field_terms.get(concept_id, live_entry.get("term", concept_id)),
                "concept_id": concept_id,
                "median_lifespan_days": int(round(median(lifespans))),
                "mean_lifespan_days": int(round(mean(lifespans))),
                "pct_filled_under_7d": round(
                    (sum(days <= 7 for days in lifespans) / len(lifespans)) * 100,
                    1,
                ),
                "pct_open_over_60d": round(
                    (sum(days > 60 for days in lifespans) / len(lifespans)) * 100,
                    1,
                ),
                "sample_size": len(lifespans),
            }
        )

    occupation_fields.sort(
        key=lambda item: item["median_lifespan_days"],
        reverse=True,
    )

    all_lifespans = [days for values in closed_lifespans.values() for days in values]
    today = date.today()
    longest_running_ads = []
    for hit in oldest_live.get("hits", []):
        published = parse_date_string(hit.get("publication_date"))
        if not published:
            continue
        occupation_field = hit.get("occupation_field") or {}
        workplace_address = hit.get("workplace_address") or {}
        longest_running_ads.append(
            {
                "id": hit.get("id"),
                "headline": hit.get("headline") or "",
                "occupation_field": occupation_field.get("label") or "—",
                "days_open": (today - published).days,
                "region": workplace_address.get("region") or "—",
            }
        )
    longest_running_ads.sort(key=lambda item: item["days_open"], reverse=True)

    payload = {
        "last_updated": date.today().isoformat(),
        "weeks_tracked": len(history),
        "occupation_fields": occupation_fields,
        "overall": {
            "median_lifespan_days": int(round(median(all_lifespans))),
            "mean_lifespan_days": int(round(mean(all_lifespans))),
            "longest_running_ads": longest_running_ads[:10],
        },
        "method_note": (
            "Field-level lifespan statistics are built from closed archive ads for the "
            f"{args.year} publication year. Longest-running ads are fetched live."
        ),
    }

    try:
        safe_write(str(Path(args.output)), payload)
    except OSError as exc:
        print(exc)
        return 1

    print(
        f"Wrote {args.output} with {len(payload['occupation_fields'])} "
        f"occupation fields."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
