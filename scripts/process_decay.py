import argparse
import io
import json
import os
import sys
import tempfile
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import requests

from collect import safe_write


# Occupation decay depends on normalized occupation-field taxonomy, so this
# script must use the enriched yearly archives rather than the raw archive.
BASE_ARCHIVE_URL = "https://data.jobtechdev.se/annonser/historiska/berikade/kompletta"
DOWNLOAD_TIMEOUT = (20, 300)
CHUNK_SIZE = 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "occupation_decay.json"


class ArchiveError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Generate data/occupation_decay.json from the yearly historical "
            "JobTech ad archives."
        )
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="Number of completed calendar years to include (default: 10).",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="Override the first year to process.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Override the last year to process.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Where to write occupation_decay.json.",
    )
    return parser.parse_args()


def resolve_years(args):
    latest_completed_year = date.today().year - 1

    if args.start_year is not None and args.end_year is not None:
        start_year = args.start_year
        end_year = args.end_year
    elif args.start_year is not None:
        start_year = args.start_year
        end_year = latest_completed_year
    elif args.end_year is not None:
        end_year = args.end_year
        start_year = end_year - args.years + 1
    else:
        end_year = latest_completed_year
        start_year = end_year - args.years + 1

    if start_year > end_year:
        raise ArchiveError("start-year must be less than or equal to end-year.")
    if start_year < 2006:
        raise ArchiveError("Historical archive starts at 2006.")

    return list(range(start_year, end_year + 1))


def archive_url(year):
    return f"{BASE_ARCHIVE_URL}/{year}_beta1_jsonl.zip"


def download_archive(year):
    url = archive_url(year)
    tmp_path = None

    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
            if response.status_code != 200:
                raise ArchiveError(f"Archive error: HTTP {response.status_code} for {url}")

            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=f"-{year}.zip",
                delete=False,
            ) as tmp:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        tmp.write(chunk)
                tmp_path = tmp.name
    except requests.RequestException as exc:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise ArchiveError(str(exc)) from None

    return tmp_path


def get_zip_member_name(zip_file):
    for name in zip_file.namelist():
        if name.endswith(".jsonl"):
            return name

    for name in zip_file.namelist():
        if not name.endswith("/"):
            return name

    raise ArchiveError("Archive did not contain a JSONL member.")


def normalize_taxonomy_item(value):
    if isinstance(value, list):
        for item in value:
            normalized = normalize_taxonomy_item(item)
            if normalized:
                return normalized
        return None

    if isinstance(value, dict):
        concept_id = (
            value.get("concept_id")
            or value.get("conceptId")
            or value.get("id")
            or value.get("code")
            or value.get("legacy_ams_taxonomy_id")
        )
        term = (
            value.get("term")
            or value.get("label")
            or value.get("name")
            or value.get("preferred_label")
        )
        if concept_id or term:
            concept_id = str(concept_id or term)
            term = str(term or concept_id)
            return {
                "concept_id": concept_id,
                "term": term,
            }
        return None

    if isinstance(value, str):
        text = value.strip()
        if text:
            return {
                "concept_id": text,
                "term": text,
            }

    return None


def extract_occupation_field(record):
    candidate_keys = (
        "occupation_field",
        "occupation-field",
        "occupationField",
    )

    for key in candidate_keys:
        normalized = normalize_taxonomy_item(record.get(key))
        if normalized:
            return normalized

    return None


def process_year(year):
    archive_path = download_archive(year)
    counts = defaultdict(int)
    terms = {}
    processed = 0
    matched = 0

    try:
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
                                f"Unexpected archive content in {year} at line {line_number}: {exc}"
                            ) from None

                        processed += 1
                        occupation_field = extract_occupation_field(record)
                        if not occupation_field:
                            continue

                        concept_id = occupation_field["concept_id"]
                        term = occupation_field["term"]
                        counts[concept_id] += 1
                        matched += 1

                        if concept_id not in terms or not terms[concept_id]:
                            terms[concept_id] = term
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"Archive for {year} is not a valid zip file: {exc}") from None
    finally:
        if archive_path and os.path.exists(archive_path):
            os.remove(archive_path)

    if processed > 0 and matched == 0:
        raise ArchiveError(
            f"Archive for {year} did not contain usable occupation_field data."
        )

    entries = [
        {
            "concept_id": concept_id,
            "term": terms[concept_id],
            "count": count,
        }
        for concept_id, count in counts.items()
    ]
    entries.sort(key=lambda item: item["count"], reverse=True)
    return entries, processed, matched


def build_output(years, per_year_entries):
    fields = {}

    for year in years:
        for entry in per_year_entries[year]:
            field = fields.setdefault(
                entry["concept_id"],
                {
                    "concept_id": entry["concept_id"],
                    "term": entry["term"],
                    "counts": {existing_year: 0 for existing_year in years},
                },
            )
            if not field["term"] and entry["term"]:
                field["term"] = entry["term"]
            field["counts"][year] = int(entry["count"])

    occupation_fields = [
        {
            "concept_id": field["concept_id"],
            "term": field["term"],
            "by_year": [field["counts"][year] for year in years],
        }
        for field in fields.values()
    ]

    occupation_fields.sort(
        key=lambda item: (
            item["by_year"][-1],
            sum(item["by_year"]),
            item["term"],
        ),
        reverse=True,
    )

    return {
        "generated": date.today().isoformat(),
        "years": years,
        "occupation_fields": occupation_fields,
    }


def main():
    args = parse_args()

    try:
        years = resolve_years(args)
    except ArchiveError as exc:
        print(exc)
        return 1

    output_path = Path(args.output)
    per_year_entries = {}

    print(
        f"Generating occupation decay data for {years[0]}-{years[-1]} "
        f"({len(years)} years)."
    )

    for year in years:
        print(f"Downloading and processing {year}...")
        try:
            entries, processed, matched = process_year(year)
        except ArchiveError as exc:
            print(exc)
            return 1

        per_year_entries[year] = entries
        print(
            f"{year}: processed {processed} ads, matched {matched} ads with occupation fields, "
            f"{len(entries)} unique fields."
        )

    payload = build_output(years, per_year_entries)

    try:
        safe_write(str(output_path), payload)
    except OSError as exc:
        print(exc)
        return 1

    print(
        f"Wrote {output_path} with {len(payload['occupation_fields'])} "
        f"occupation fields across {len(years)} years."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
