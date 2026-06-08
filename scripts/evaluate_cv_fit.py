#!/usr/bin/env python3
"""Evaluate the END-TO-END /cv-fit analysis on the labelled synthetic CVs.

Unlike scripts/evaluate_neural_cv_fit.py (which benchmarks only the retrieval
backends through bucket()), this runs the full endpoint pipeline
(cv_fit_core.analyze_cv) in the deterministic TF-IDF mode — no GPU — and scores
the things a user actually sees:

  - domain routing      : primary_domain == expect_domain
  - top-3 domain hit    : expected domain appears in the first 3 best/adjacent
  - no-collapse         : must_not_top roles never appear in any shown bucket
  - occupation-group    : matched_occupation_group matches expect_group (the
                          analyst-vs-developer lane routing inside a field)
  - gap relevance       : gap_forbidden skills never surface (e.g. no C++/Java
                          for a data analyst)

Labels live on bm.SYNTHETIC_CVS. Writes data/cv_fit_eval.json and prints a
report. With --strict, exits non-zero on any group misroute, gap leak, or
domain accuracy below --min-domain-accuracy (use in CI to catch regressions).

    python3 scripts/evaluate_cv_fit.py
    python3 scripts/evaluate_cv_fit.py --strict
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
ENDPOINT_DIR = os.path.join(ROOT, "nebius", "cv_fit_endpoint")
sys.path.insert(0, HERE)
sys.path.insert(0, ENDPOINT_DIR)

import build_cv_match_index as bm   # noqa: E402
# Force the deterministic path regardless of the caller's environment.
os.environ.pop("CV_FIT_LLM_MODEL", None)
os.environ.pop("CV_FIT_EMBEDDING_MODEL", None)
import cv_fit_core                  # noqa: E402


def _contains_any(text, needles):
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


def evaluate():
    engine = cv_fit_core.get_engine()
    title_role = {r["title"]: r["role_id"] for r in engine.catalog}
    title_domain = {r["title"]: r["domain"] for r in engine.catalog}

    rows = []
    dom_hits = top3_hits = collapse_ok = 0
    grp_total = grp_ok = gap_total = gap_ok = 0
    for cv in bm.SYNTHETIC_CVS:
        rep = cv_fit_core.analyze_cv(cv["text"])
        shown = rep["best_fit_roles"] + rep["adjacent_roles"] + rep["not_your_main_lane_roles"]
        shown_ids = {title_role.get(t) for t in shown}

        dom_ok = rep["primary_domain"] == cv["expect_domain"]
        top3_doms = [title_domain.get(t) for t in (rep["best_fit_roles"] + rep["adjacent_roles"])[:3]]
        top3_ok = cv["expect_domain"] in top3_doms
        no_collapse = not (cv.get("must_not_top", set()) & shown_ids)
        dom_hits += int(dom_ok); top3_hits += int(top3_ok); collapse_ok += int(no_collapse)

        group = rep.get("matched_occupation_group")
        grp_check = None
        if cv.get("expect_group"):
            grp_total += 1
            grp_check = bool(group) and _contains_any(group, cv["expect_group"])
            grp_ok += int(grp_check)

        gap_check = None
        if cv.get("gap_forbidden"):
            gap_total += 1
            leaked = [g for g in rep["missing_skills"] if _contains_any(g, cv["gap_forbidden"])]
            gap_check = not leaked
            gap_ok += int(gap_check)

        rows.append({
            "cv": cv["name"], "primary_domain": rep["primary_domain"],
            "expected_domain": cv["expect_domain"], "domain_hit": dom_ok,
            "top3_domain_hit": top3_ok, "no_collapse": no_collapse,
            "matched_occupation_group": group, "group_ok": grp_check,
            "gap_ok": gap_check, "missing_skills": rep["missing_skills"],
            "best": rep["best_fit_roles"][:3],
        })

    n = len(bm.SYNTHETIC_CVS) or 1
    summary = {
        "n_cvs": n,
        "domain_accuracy": round(dom_hits / n, 3),
        "top3_domain_hit": round(top3_hits / n, 3),
        "no_collapse_rate": round(collapse_ok / n, 3),
        "group_routing_accuracy": round(grp_ok / grp_total, 3) if grp_total else None,
        "group_routing_n": grp_total,
        "gap_relevance_rate": round(gap_ok / gap_total, 3) if gap_total else None,
        "gap_relevance_n": gap_total,
        "backend": engine.backend,
    }
    return summary, rows


def main():
    ap = argparse.ArgumentParser(description="End-to-end /cv-fit evaluation on labelled CVs.")
    ap.add_argument("--out", default=os.path.join(DATA_DIR, "cv_fit_eval.json"))
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on group misroute, gap leak, or low domain accuracy")
    ap.add_argument("--min-domain-accuracy", type=float, default=0.9)
    args = ap.parse_args()

    summary, rows = evaluate()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"generated": now, "summary": summary, "per_cv": rows}
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, args.out)

    print(f"CV-fit evaluation ({summary['n_cvs']} CVs, backend={summary['backend']})")
    print(f"  domain accuracy      : {summary['domain_accuracy']}")
    print(f"  top-3 domain hit     : {summary['top3_domain_hit']}")
    print(f"  no-collapse rate     : {summary['no_collapse_rate']}")
    print(f"  group routing acc    : {summary['group_routing_accuracy']} (n={summary['group_routing_n']})")
    print(f"  gap relevance rate   : {summary['gap_relevance_rate']} (n={summary['gap_relevance_n']})")
    print()
    for r in rows:
        flags = []
        if not r["domain_hit"]:
            flags.append(f"DOMAIN!={r['expected_domain']}")
        if not r["no_collapse"]:
            flags.append("COLLAPSE")
        if r["group_ok"] is False:
            flags.append(f"GROUP={r['matched_occupation_group']!r}")
        if r["gap_ok"] is False:
            flags.append("GAP-LEAK")
        mark = "  ok" if not flags else "FAIL"
        print(f"  [{mark}] {r['cv'][:34]:34} -> {r['primary_domain']:14} "
              f"{('· ' + ', '.join(flags)) if flags else ''}")
    print(f"\nWrote {args.out}")

    if args.strict:
        bad = [r for r in rows if r["group_ok"] is False or r["gap_ok"] is False]
        if bad or summary["domain_accuracy"] < args.min_domain_accuracy:
            print(f"STRICT: {len(bad)} routing/gap failures; "
                  f"domain accuracy {summary['domain_accuracy']} (min {args.min_domain_accuracy}).")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
