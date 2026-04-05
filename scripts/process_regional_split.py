import os
import sys
from datetime import datetime, timezone

try:
    from collect import (
        ApiRequestError,
        DATA_DIR,
        LIVE_PATH,
        deduplicate,
        fetch_search,
        load_json,
        parse_stat,
        safe_write,
    )
except ModuleNotFoundError:
    from scripts.collect import (
        ApiRequestError,
        DATA_DIR,
        LIVE_PATH,
        deduplicate,
        fetch_search,
        load_json,
        parse_stat,
        safe_write,
    )


REGIONAL_SPLIT_PATH = os.path.join(DATA_DIR, "regional_split.json")
REGIONS = [
    ("CifL_Rzy_Mku", "Stockholms län"),
    ("zBon_eET_fFU", "Uppsala län"),
    ("s93u_BEb_sx2", "Södermanlands län"),
    ("oLT3_Q9p_3nn", "Östergötlands län"),
    ("MtbE_xWT_eMi", "Jönköpings län"),
    ("tF3y_MF9_h5G", "Kronobergs län"),
    ("9QUH_2bb_6Np", "Kalmar län"),
    ("K8iD_VQv_2BA", "Gotlands län"),
    ("DQZd_uYs_oKb", "Blekinge län"),
    ("CaRE_1nn_cSU", "Skåne län"),
    ("wjee_qH2_yb6", "Hallands län"),
    ("zdoY_6u5_Krt", "Västra Götalands län"),
    ("EVVp_h6U_GSZ", "Värmlands län"),
    ("xTCk_nT5_Zjm", "Örebro län"),
    ("G6DV_fKE_Viz", "Västmanlands län"),
    ("oDpK_oZ2_WYt", "Dalarnas län"),
    ("zupA_8Nt_xcD", "Gävleborgs län"),
    ("NvUF_SP1_1zo", "Västernorrlands län"),
    ("65Ms_7r1_RTG", "Jämtlands län"),
    ("g5Tt_CAV_zBd", "Västerbottens län"),
    ("9hXe_F4g_eTG", "Norrbottens län"),
]


def load_live_snapshot():
    snapshot = load_json(LIVE_PATH, {})
    if not isinstance(snapshot, dict) or not snapshot.get("week"):
        raise ApiRequestError(
            "Live snapshot is missing or invalid. Run scripts/collect.py first."
        )
    return snapshot


def build_region_recent_weeks(previous_payload, current_region, current_week):
    previous_regions = {}
    if isinstance(previous_payload, dict):
        for region in previous_payload.get("regions", []):
            if isinstance(region, dict) and region.get("concept_id"):
                previous_regions[region["concept_id"]] = region

    previous = previous_regions.get(current_region["concept_id"], {})
    recent = []
    for item in previous.get("recent_weeks", []):
        if not isinstance(item, dict) or item.get("week") == current_week:
            continue
        recent.append(item)

    top_field = max(
        current_region["occupation_fields"],
        key=lambda entry: entry["vs_national"],
        default=None,
    )
    recent.append(
        {
            "week": current_week,
            "total_ads": current_region["total_ads"],
            "top_field": {
                "term": top_field["term"],
                "vs_national": top_field["vs_national"],
            }
            if top_field
            else None,
        }
    )
    return recent[-4:]


def build_payload(live_snapshot):
    previous_payload = load_json(REGIONAL_SPLIT_PATH, {})
    national_response = fetch_search(
        [
            ("limit", 0),
            ("stats", "occupation-field"),
            ("stats.limit", 30),
        ]
    )
    national_fields = deduplicate(
        parse_stat(national_response.get("stats", []), "occupation-field")
    )
    national_total_ads = sum(
        int(entry.get("count", 0)) for entry in national_fields if entry.get("count")
    )
    if national_total_ads <= 0:
        raise ApiRequestError("Live snapshot does not contain occupation field totals.")

    national_shares = {}
    national_terms = {}
    for entry in national_fields:
        concept_id = entry.get("concept_id")
        count = int(entry.get("count", 0))
        if not concept_id or count <= 0:
            continue
        national_shares[concept_id] = count / national_total_ads
        national_terms[concept_id] = entry.get("term", concept_id)

    regions = []
    for region_id, region_term in REGIONS:
        response = fetch_search(
            [
                ("limit", 0),
                ("region", region_id),
                ("stats", "occupation-field"),
                ("stats.limit", 30),
            ]
        )
        try:
            region_total = int(response["total"]["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiRequestError(f"Unexpected response shape: {exc}") from None

        region_fields = deduplicate(
            parse_stat(response.get("stats", []), "occupation-field")
        )
        region_counts = {
            entry["concept_id"]: int(entry["count"])
            for entry in region_fields
            if entry.get("concept_id")
        }

        occupation_fields = []
        for concept_id, national_share in national_shares.items():
            count = region_counts.get(concept_id, 0)
            regional_share = (count / region_total) if region_total else 0
            vs_national = (regional_share / national_share) if national_share else 0
            occupation_fields.append(
                {
                    "concept_id": concept_id,
                    "term": national_terms[concept_id],
                    "count": count,
                    "regional_share": round(regional_share, 4),
                    "vs_national": round(vs_national, 2),
                }
            )

        region_payload = {
            "concept_id": region_id,
            "term": region_term,
            "total_ads": region_total,
            "occupation_fields": occupation_fields,
        }
        region_payload["recent_weeks"] = build_region_recent_weeks(
            previous_payload,
            region_payload,
            live_snapshot["week"],
        )
        regions.append(region_payload)

    return {
        "week": live_snapshot["week"],
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "national_shares": {
            concept_id: round(share, 4)
            for concept_id, share in national_shares.items()
        },
        "regions": regions,
    }


def main():
    try:
        live_snapshot = load_live_snapshot()
        payload = build_payload(live_snapshot)
        safe_write(REGIONAL_SPLIT_PATH, payload)
    except (ApiRequestError, OSError) as exc:
        print(exc)
        return 1

    print(
        f"Wrote {REGIONAL_SPLIT_PATH} for {payload['week']} with "
        f"{len(payload['regions'])} regions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
