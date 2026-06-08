#!/usr/bin/env python3
"""Build data/field_skills.json — the skills real job ads request, per occupation
field AND per occupation group — from JobTech's enriched historical archive.

This is the data behind the CV "skill gaps": for a CV's field/group we compare
what the candidate has against what those ads actually ask for, instead of a
hand-written role-skill list. Same source and extraction as
process_skill_velocity.py (must_have + nice_to_have skills per ad).

Two granularities are produced per field:
  * field level  — top skills across the whole occupation field (the fallback)
  * group level  — top skills per occupation GROUP (SSYK-4) inside the field,
                   so a data analyst is matched to the analyst/architect group's
                   demand rather than the dev-dominated whole "Data/IT" field.

Occupation groups are sparser than fields, so by default we aggregate the two
most recent completed years to keep per-group counts meaningful, and only emit
groups with at least --min-group-ads ads that carry skills.

Run (downloads the archives it needs):
    python3 scripts/process_field_skills.py                 # last 2 years
    python3 scripts/process_field_skills.py --years 2024 2025
    python3 scripts/process_field_skills.py --archive /tmp/2025.zip --archive /tmp/2024.zip
"""
import argparse
import io
import json
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

try:
    from collect import safe_write
    from process_decay import ArchiveError, download_archive, get_zip_member_name
    from process_skill_velocity import normalize_skill_entries, normalize_occupation_field
except ModuleNotFoundError:
    from scripts.collect import safe_write
    from scripts.process_decay import ArchiveError, download_archive, get_zip_member_name
    from scripts.process_skill_velocity import normalize_skill_entries, normalize_occupation_field

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "data" / "field_skills.json"


def normalize_occupation_group(record):
    """(concept_id, term) for the ad's occupation group (SSYK-4), or None.

    Mirrors normalize_occupation_field but reads the finer 'occupation_group'
    taxonomy level so demand can be aggregated per group inside a field.
    """
    value = record.get("occupation_group")
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, dict):
        return None
    concept_id = value.get("concept_id")
    term = value.get("label") or value.get("term")
    if not concept_id or not term:
        return None
    return concept_id, term


class _Accumulator:
    """Counts skill demand per occupation field and per occupation group."""

    def __init__(self):
        self.field_terms = {}
        self.group_terms = {}
        self.group_field = {}                                   # group_id -> field_id
        self.field_ad_counts = defaultdict(int)
        self.group_ad_counts = defaultdict(int)
        self.field_skill_counts = defaultdict(lambda: defaultdict(int))
        self.group_skill_counts = defaultdict(lambda: defaultdict(int))
        self.skill_terms = {}
        self.processed = 0
        self.matched = 0

    def add_record(self, record):
        self.processed += 1
        of = normalize_occupation_field(record)
        if not of:
            return
        field_id, field_term = of
        self.field_terms[field_id] = field_term

        ad_skills = {}
        for bucket in ("must_have", "nice_to_have"):
            requirements = record.get(bucket) or {}
            for cid, term in normalize_skill_entries(requirements.get("skills")):
                ad_skills.setdefault(cid, term)
        if not ad_skills:
            return

        self.matched += 1
        self.field_ad_counts[field_id] += 1
        og = normalize_occupation_group(record)
        if og:
            group_id, group_term = og
            self.group_terms[group_id] = group_term
            self.group_field[group_id] = field_id
            self.group_ad_counts[group_id] += 1
        for cid, term in ad_skills.items():
            self.field_skill_counts[field_id][cid] += 1
            if og:
                self.group_skill_counts[og[0]][cid] += 1
            self.skill_terms.setdefault(cid, term)


def consume_archive(archive_path, acc):
    with zipfile.ZipFile(archive_path) as archive:
        member = get_zip_member_name(archive)
        with archive.open(member) as raw, io.TextIOWrapper(raw, encoding="utf-8") as fh:
            for line in fh:
                row = line.strip()
                if not row:
                    continue
                try:
                    record = json.loads(row)
                except json.JSONDecodeError:
                    continue
                acc.add_record(record)
                if acc.processed % 200000 == 0:
                    print(f"  …{acc.processed} ads ({acc.matched} with skills)")


def _ranked_skills(counts, skill_terms, ads, top):
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [
        {"concept_id": cid, "term": skill_terms[cid], "count": c,
         "share": round(c / ads, 4)}
        for cid, c in ranked
    ]


def main():
    ap = argparse.ArgumentParser(description="Per-field and per-group skill demand from JobTech ads.")
    ap.add_argument("--year", type=int, help="A single year to process (back-compat).")
    ap.add_argument("--years", type=int, nargs="+",
                    help="Explicit years to aggregate (default: the two most recent completed years).")
    ap.add_argument("--archive", action="append", default=[],
                    help="Pre-downloaded archive zip(s) to use instead of downloading. Repeatable.")
    ap.add_argument("--top", type=int, default=30, help="top skills kept per field")
    ap.add_argument("--group-top", type=int, default=20, help="top skills kept per occupation group")
    ap.add_argument("--min-group-ads", type=int, default=12,
                    help="drop occupation groups with fewer ads carrying skills (too sparse to trust)")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    if args.year is not None:
        years = [args.year]
    elif args.years:
        years = sorted(set(args.years))
    else:
        last = date.today().year - 1
        years = [last - 1, last]

    acc = _Accumulator()
    sources = []
    if args.archive:
        import re
        for path in args.archive:
            print(f"Reading {path}…")
            consume_archive(path, acc)
            m = re.search(r"(20\d\d)", Path(path).name)      # prefer a clean year label
            sources.append(m.group(1) if m else Path(path).name)
    else:
        for year in years:
            print(f"Downloading {year} enriched archive…")
            archive_path = download_archive(year)
            consume_archive(archive_path, acc)
            sources.append(str(year))

    # Group skills nested under their parent field. Sparse groups are dropped so
    # the endpoint never grounds advice on a handful of ads.
    groups_by_field = defaultdict(dict)
    kept_groups = 0
    for gid, counts in acc.group_skill_counts.items():
        ads = acc.group_ad_counts[gid]
        if ads < args.min_group_ads:
            continue
        fid = acc.group_field.get(gid)
        if not fid:
            continue
        groups_by_field[fid][gid] = {
            "group_term": acc.group_terms.get(gid),
            "ads_with_skills": ads,
            "skills": _ranked_skills(counts, acc.skill_terms, ads, args.group_top),
        }
        kept_groups += 1

    fields_out = {}
    for fid, counts in acc.field_skill_counts.items():
        ads = acc.field_ad_counts[fid] or 1
        fields_out[fid] = {
            "field_term": acc.field_terms.get(fid),
            "ads_with_skills": acc.field_ad_counts[fid],
            "skills": _ranked_skills(counts, acc.skill_terms, ads, args.top),
            "groups": groups_by_field.get(fid, {}),
        }

    payload = {
        "last_updated": date.today().isoformat(),
        "years": sources,
        "source": "JobTech enriched historical ads (must_have + nice_to_have skills), per field and occupation group",
        "min_group_ads": args.min_group_ads,
        "fields": fields_out,
    }
    safe_write(args.output, payload)
    print(f"Processed {acc.processed} ads, {acc.matched} with skills, "
          f"{len(fields_out)} fields, {kept_groups} groups (>= {args.min_group_ads} ads). "
          f"Wrote {args.output}")


if __name__ == "__main__":
    raise SystemExit(main())
