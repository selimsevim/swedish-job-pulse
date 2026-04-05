import argparse
import io
import json
import os
import sys
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

try:
    from collect import safe_write
except ModuleNotFoundError:
    from scripts.collect import safe_write

try:
    from process_decay import ArchiveError, download_archive, get_zip_member_name
except ModuleNotFoundError:
    from scripts.process_decay import ArchiveError, download_archive, get_zip_member_name


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "skill_velocity.json"
TECHNICAL_FIELD_ID = "apaJ_2ja_LuF"
HEALTHCARE_FIELD_ID = "NYW6_mP6_vwf"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate data/skill_velocity.json from enriched historical archives."
    )
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--min-total", type=int, default=25)
    parser.add_argument("--min-current", type=int, default=1)
    parser.add_argument("--max-skills", type=int, default=500)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def resolve_years(args):
    latest_completed_year = date.today().year - 1
    end_year = args.end_year or latest_completed_year
    start_year = args.start_year or max(2016, end_year - 1)

    if start_year > end_year:
        raise ArchiveError("start-year must be less than or equal to end-year.")
    if start_year < 2016:
        raise ArchiveError("Skill velocity archive starts at 2016.")

    return list(range(start_year, end_year + 1))


def month_range(years):
    months = []
    for year in years:
        for month in range(1, 13):
            months.append(f"{year}-{month:02d}")
    return months


def normalize_skill_entries(value):
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
        term = item.get("label") or item.get("term")
        if not concept_id or not term or concept_id in seen:
            continue
        seen.add(concept_id)
        entries.append((concept_id, term))
    return entries


def normalize_occupation_field(record):
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


def percent_change(previous_value, current_value):
    previous = float(previous_value or 0)
    current = float(current_value or 0)
    if previous <= 0:
        return round(100.0 if current > 0 else 0.0, 1)
    return round(((current - previous) / previous) * 100, 1)


def rolling_change(values, window):
    if not values:
        return 0.0

    trailing = sum(values[-window:])
    previous = sum(values[-(window * 2):-window]) if len(values) >= window * 2 else sum(values[:-window])
    return percent_change(previous, trailing)


def main():
    args = parse_args()

    try:
        years = resolve_years(args)
    except ArchiveError as exc:
        print(exc)
        return 1

    months = month_range(years)
    monthly_counts = defaultdict(lambda: defaultdict(int))
    terms = {}
    first_seen = {}
    technical_counts = defaultdict(int)
    healthcare_counts = defaultdict(int)

    print(
        f"Generating skill velocity data for {years[0]}-{years[-1]} "
        f"({len(months)} months)."
    )

    for year in years:
        print(f"Downloading and processing {year}...")
        archive_path = None
        processed = 0
        matched = 0

        try:
            archive_path = download_archive(year)
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
                            published = str(record.get("publication_date") or "")[:7]
                            if published not in months:
                                continue

                            ad_skills = {}
                            for bucket in ("must_have", "nice_to_have"):
                                requirements = record.get(bucket) or {}
                                for concept_id, term in normalize_skill_entries(
                                    requirements.get("skills")
                                ):
                                    ad_skills.setdefault(concept_id, term)

                            if not ad_skills:
                                continue

                            matched += 1
                            occupation_field = normalize_occupation_field(record)
                            for concept_id, term in ad_skills.items():
                                monthly_counts[concept_id][published] += 1
                                terms.setdefault(concept_id, term)
                                first_seen.setdefault(concept_id, published)
                                if occupation_field:
                                    field_id, _ = occupation_field
                                    if field_id == TECHNICAL_FIELD_ID:
                                        technical_counts[concept_id] += 1
                                    elif field_id == HEALTHCARE_FIELD_ID:
                                        healthcare_counts[concept_id] += 1
        except ArchiveError as exc:
            print(exc)
            return 1
        finally:
            if archive_path and os.path.exists(archive_path):
                os.remove(archive_path)

        print(
            f"{year}: processed {processed} ads, matched {matched} ads with skills."
        )

    skill_rows = []
    for concept_id, counts_by_month in monthly_counts.items():
        series = [counts_by_month.get(month, 0) for month in months]
        total_mentions = sum(series)
        latest_count = series[-1] if series else 0
        if total_mentions < args.min_total:
            continue
        if latest_count < args.min_current:
            continue

        peak_count = max(series)
        if peak_count <= 0:
            continue

        peak_index = series.index(peak_count)
        skill_rows.append(
            {
                "concept_id": concept_id,
                "term": terms.get(concept_id, concept_id),
                "monthly_counts": series,
                "growth_90d": rolling_change(series, 3),
                "growth_365d": rolling_change(series, 12),
                "first_seen": first_seen.get(concept_id, months[0]),
                "peak_month": months[peak_index],
                "peak_count": peak_count,
                "latest_count": latest_count,
                "total_mentions": total_mentions,
            }
        )

    skill_rows.sort(
        key=lambda item: (
            item["total_mentions"],
            item["peak_count"],
            item["term"].lower(),
        ),
        reverse=True,
    )
    skill_rows = skill_rows[: args.max_skills]

    payload = {
        "last_updated": date.today().isoformat(),
        "months": months,
        "skills": [
            {
                "concept_id": row["concept_id"],
                "term": row["term"],
                "monthly_counts": row["monthly_counts"],
                "growth_90d": row["growth_90d"],
                "growth_365d": row["growth_365d"],
                "first_seen": row["first_seen"],
                "peak_month": row["peak_month"],
                "peak_count": row["peak_count"],
                "latest_count": row["latest_count"],
            }
            for row in skill_rows
        ],
        "technical_skill_ids": sorted(
            row["concept_id"]
            for row in skill_rows
            if technical_counts.get(row["concept_id"], 0) > 0
        ),
        "healthcare_skill_ids": sorted(
            row["concept_id"]
            for row in skill_rows
            if healthcare_counts.get(row["concept_id"], 0) > 0
        ),
    }

    try:
        safe_write(str(Path(args.output)), payload)
    except OSError as exc:
        print(exc)
        return 1

    print(
        f"Wrote {args.output} with {len(payload['skills'])} skills "
        f"across {len(payload['months'])} months."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
