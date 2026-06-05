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
    "main_answer", "primary_domain", "domain_label", "best_fit_roles",
    "adjacent_roles", "not_your_main_lane_roles", "missing_skills",
    "cv_improvements", "search_keywords", "action_plan_7_day",
    "market_signal", "backend", "extracted",
}


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


if __name__ == "__main__":
    main()
