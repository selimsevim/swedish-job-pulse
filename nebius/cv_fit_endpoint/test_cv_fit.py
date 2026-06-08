"""Smoke test for the /cv-fit core on a synthetic CV (no server, no model).

Runs the TF-IDF fallback (standard library only) and checks the report shape +
that a senior SFMC/Martech CV is NOT collapsed into generic roles.

    python3 nebius/cv_fit_endpoint/test_cv_fit.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cv_fit_core  # noqa: E402

EXPECTED_KEYS = {
    "main_answer", "why_recommendation", "primary_domain", "domain_label",
    "best_fit_roles", "adjacent_roles", "not_your_main_lane_roles", "missing_skills",
    "matched_occupation_group", "cv_improvements", "search_keywords", "action_plan_7_day",
    "market_signal", "backend", "extracted",
}

# A data analyst sits in the dev-dominated "Data/IT" field, so whole-field gap
# demand would push C++/Java at them. Occupation-GROUP granularity must route the
# gaps to the analyst/architect group instead.
DATA_ANALYST_CV = (
    "Mira Holm — Data Analyst, 4 years. SQL, Python, Power BI and Excel. "
    "Built dashboards and KPI reporting for the commercial team. Strong statistics."
)


def check_data_analyst_group():
    report = cv_fit_core.analyze_cv(DATA_ANALYST_CV)
    assert report["primary_domain"] == "data_analytics", report["primary_domain"]
    group = (report.get("matched_occupation_group") or "").lower()
    assert "analytiker" in group or "arkitekt" in group, \
        f"expected analyst/architect occupation group, got {report.get('matched_occupation_group')!r}"
    gaps = " ".join(report["missing_skills"]).lower()
    for dev_only in ("c++", "java", "linux"):
        assert dev_only not in gaps, \
            f"dev-only skill leaked into analyst gaps: {dev_only} ({report['missing_skills']})"
    print(f"OK — data analyst routed to group '{report['matched_occupation_group']}' "
          f"(no dev-only gaps): {report['missing_skills']}")


def main():
    with open(os.path.join(HERE, "test_payload.json"), "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    report = cv_fit_core.analyze_cv(
        payload["cv_text"], region=payload.get("region"),
        swedish_level=payload.get("swedish_level"), target_role=payload.get("target_role"),
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))

    assert EXPECTED_KEYS.issubset(report.keys()), "missing report keys"
    assert report["primary_domain"] == "crm_martech", report["primary_domain"]
    best = " ".join(report["best_fit_roles"]).lower()
    assert "salesforce marketing cloud" in best or "martech" in best, "expected martech best-fit"
    not_lane = " ".join(report["not_your_main_lane_roles"]).lower()
    assert "seo" in not_lane or "social media" in not_lane or "digital marketing" in not_lane, \
        "expected digital-marketing roles flagged as not-your-main-lane"
    # No-collapse: generic roles must not be best-fit.
    for bad in ("seo specialist", "social media specialist", "software developer"):
        assert bad not in best, f"collapsed into generic role: {bad}"

    print("\nOK — report shape valid, SFMC CV mapped to martech (no collapse). "
          f"backend={report['backend']}")

    check_data_analyst_group()


if __name__ == "__main__":
    main()
