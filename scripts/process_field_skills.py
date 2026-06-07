#!/usr/bin/env python3
"""Build data/field_skills.json — the skills real job ads request, per occupation
field — from JobTech's enriched historical archive.

This is the data behind the CV "skill gaps": for a CV's field we compare what the
candidate has against what that field's ads actually ask for, instead of a
hand-written role-skill list. Same source and extraction as
process_skill_velocity.py (must_have + nice_to_have skills per ad), but
aggregated PER occupation field.

Run (one recent year is enough for current demand):
    python3 scripts/process_field_skills.py --year 2025
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


def main():
    ap = argparse.ArgumentParser(description="Per-field skill demand from JobTech ads.")
    ap.add_argument("--year", type=int, default=date.today().year - 1)
    ap.add_argument("--top", type=int, default=30, help="top skills kept per field")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    field_terms = {}
    field_skill_counts = defaultdict(lambda: defaultdict(int))
    skill_terms = {}
    field_ad_counts = defaultdict(int)

    print(f"Downloading {args.year} enriched archive…")
    archive_path = download_archive(args.year)
    processed = matched = 0
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
                processed += 1
                of = normalize_occupation_field(record)
                if not of:
                    continue
                field_id, field_term = of
                field_terms[field_id] = field_term
                ad_skills = {}
                for bucket in ("must_have", "nice_to_have"):
                    requirements = record.get(bucket) or {}
                    for cid, term in normalize_skill_entries(requirements.get("skills")):
                        ad_skills.setdefault(cid, term)
                if not ad_skills:
                    continue
                matched += 1
                field_ad_counts[field_id] += 1
                for cid, term in ad_skills.items():
                    field_skill_counts[field_id][cid] += 1
                    skill_terms.setdefault(cid, term)
                if processed % 200000 == 0:
                    print(f"  …{processed} ads ({matched} with skills)")

    fields_out = {}
    for fid, counts in field_skill_counts.items():
        ads = field_ad_counts[fid] or 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[: args.top]
        fields_out[fid] = {
            "field_term": field_terms.get(fid),
            "ads_with_skills": field_ad_counts[fid],
            "skills": [
                {"concept_id": cid, "term": skill_terms[cid], "count": c,
                 "share": round(c / ads, 4)}
                for cid, c in ranked
            ],
        }

    payload = {
        "last_updated": date.today().isoformat(),
        "year": args.year,
        "source": "JobTech enriched historical ads (must_have + nice_to_have skills)",
        "fields": fields_out,
    }
    safe_write(args.output, payload)
    print(f"Processed {processed} ads, {matched} with skills, "
          f"{len(fields_out)} fields. Wrote {args.output}")


if __name__ == "__main__":
    raise SystemExit(main())
