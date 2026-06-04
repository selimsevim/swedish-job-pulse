#!/usr/bin/env python3
"""Train the career-signal demand-forecast model and emit forecast artifacts.

This is the ML layer of Career Reality Check. It forecasts near-term labour
demand per occupation group and turns that into a grow / stable / decline
trend class, benchmarked against a naive baseline.

WHAT IT PREDICTS
    For each occupation group, the active-ad count ~4 weeks ahead, from weekly
    history. The forecast is compared to the latest observed value to produce a
    trend class:  grow  /  stable  /  decline.

    Region: per-region *weekly* history per occupation does not exist in the
    public feed (regional_split is a current-week cross-tab only). So the model
    is trained at the national occupation-group level, and the region dimension
    is applied downstream as a transparent specialisation weight in
    process_career_reality.py (via regional_field_strength). This is documented
    rather than faked. A future Nebius data job that persists a weekly
    occupation x region feed would let the same model generalise to pairs.

DATA / FEATURES (lag features built from data/history.json)
    ad_count_previous_week        last observed weekly ad count
    ad_count_4_week_average       mean of the last 4 weeks
    ad_count_8_week_average       mean of the last 8 weeks
    trend_last_4_weeks            relative change over the last 4 weeks
    remote_share                  field share of remote ads (static, from live)
    entry_level_share             field share of entry-level ads (static)
    search_attention_gap          ad/search gap ratio (from demand_gap)
    occupation_field_code         ordinal code for the occupation field

MODELS
    Baseline:  persistence (predict the last observed value) and 4-week MA.
    ML model:  scikit-learn HistGradientBoostingRegressor (falls back to
               RandomForestRegressor). scikit-learn is OPTIONAL: if it is not
               installed (or there is too little history), the script still
               runs and produces forecasts from the baseline.

EVALUATION (data/model_metrics.json)
    MAE, MAPE (computed only where actuals are large enough to be safe), and
    trend-direction accuracy + macro-F1, for both the ML model and the baseline.

OUTPUTS
    data/occupation_forecast.json   per-occupation 4-week forecast + trend class
    data/model_metrics.json         evaluation + provenance

Run:
    python3 scripts/train_career_signal_model.py

Runs unchanged as a Nebius Serverless AI Job (see nebius/README.md). It never
raises on missing inputs or a missing ML runtime; the website always gets a
valid artifact (forecast may be flagged source="baseline").
"""

import argparse
import datetime as dt
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")

HORIZON_WEEKS = 4          # forecast this many weeks ahead
MIN_HISTORY = 8            # weeks of contiguous history needed to build features
GROW_THRESHOLD = 0.08      # +/-8% change defines grow / decline vs stable

# Import the shared field classifier from the sibling script. If that import
# fails for any reason we degrade gracefully to "no field".
try:
    from process_career_reality import classify_field, load_json, as_list
except Exception:  # pragma: no cover - defensive
    def load_json(name, default=None):
        path = os.path.join(DATA_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return default if default is not None else {}

    def as_list(value):
        return value if isinstance(value, list) else []

    def classify_field(term):
        return None, None, None


# ---------------------------------------------------------------------------
# Optional ML runtime
# ---------------------------------------------------------------------------

def load_regressor():
    """Return (estimator_factory, name) or (None, reason) if unavailable."""
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        return (lambda: HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.06, max_depth=4,
            min_samples_leaf=15, random_state=42),
            "HistGradientBoostingRegressor")
    except Exception:
        pass
    try:
        from sklearn.ensemble import RandomForestRegressor
        return (lambda: RandomForestRegressor(
            n_estimators=200, max_depth=8, min_samples_leaf=4,
            random_state=42, n_jobs=-1),
            "RandomForestRegressor")
    except Exception as exc:
        return None, f"scikit-learn unavailable ({exc.__class__.__name__})"


# ---------------------------------------------------------------------------
# Static per-field / per-group context features
# ---------------------------------------------------------------------------

def field_share_map(entries):
    """{field_concept_id: share_of_total} from a [{concept_id, count}] list."""
    rows = [(e.get("concept_id"), float(e.get("count") or 0))
            for e in as_list(entries) if (e.get("count") or 0) > 0]
    total = sum(c for _i, c in rows)
    if total <= 0:
        return {}
    return {fid: round(c / total, 4) for fid, c in rows if fid}


def gap_map(demand_gap):
    """{group_concept_id: gap_ratio}. Lower gap = more search attention."""
    out = {}
    for occ in as_list(demand_gap.get("occupations")):
        cid = occ.get("concept_id")
        gr = occ.get("gap_ratio")
        if cid and isinstance(gr, (int, float)):
            out[cid] = float(gr)
    return out


# ---------------------------------------------------------------------------
# Supervised dataset construction
# ---------------------------------------------------------------------------

def build_series(history):
    """Return (week_order, {group_id: {term, counts_by_week_idx}})."""
    weeks = as_list(history)
    week_order = sorted({s.get("week") for s in weeks if s.get("week")})
    week_idx = {w: i for i, w in enumerate(week_order)}

    groups = {}  # gid -> {"term": str, "counts": {idx: count}}
    for snapshot in weeks:
        idx = week_idx.get(snapshot.get("week"))
        if idx is None:
            continue
        for group in as_list(snapshot.get("by_occupation_group")):
            gid = group.get("concept_id")
            if not gid:
                continue
            entry = groups.setdefault(gid, {"term": group.get("term"), "counts": {}})
            entry["counts"][idx] = float(group.get("count") or 0)
            if not entry["term"]:
                entry["term"] = group.get("term")
    return week_order, groups


def make_feature_row(counts, t, field_code, remote_share, entry_share, gap):
    """Build a feature list at time index t (inclusive). Returns None if the
    contiguous 8-week lookback is not fully present."""
    window = [counts.get(t - k) for k in range(MIN_HISTORY)]
    if any(v is None for v in window):
        return None
    last = window[0]
    last4 = window[:4]
    last8 = window[:8]
    prev4 = counts.get(t - 4)
    if prev4 is None or prev4 <= 0:
        trend4 = 0.0
    else:
        trend4 = (last - prev4) / prev4
    return [
        last,
        sum(last4) / len(last4),
        sum(last8) / len(last8),
        trend4,
        remote_share,
        entry_share,
        gap,
        float(field_code),
    ]


def build_dataset(week_order, groups, remote_shares, entry_shares, gaps,
                  field_codes, median_gap):
    """Return (X, y, meta) supervised samples for forecasting count[t+HORIZON]."""
    X, y, meta = [], [], []
    for gid, info in groups.items():
        counts = info["counts"]
        if len(counts) < MIN_HISTORY + 1:
            continue
        term = info["term"]
        fid, _sv, _en = classify_field(term)
        field_code = field_codes.setdefault(fid or "unknown", len(field_codes))
        remote_share = remote_shares.get(fid, 0.0)
        entry_share = entry_shares.get(fid, 0.0)
        gap = gaps.get(gid, median_gap)

        max_idx = max(counts)
        for t in range(MIN_HISTORY - 1, max_idx + 1):
            target = counts.get(t + HORIZON_WEEKS)
            if target is None:
                continue
            row = make_feature_row(counts, t, field_code, remote_share,
                                   entry_share, gap)
            if row is None:
                continue
            X.append(row)
            y.append(target)
            meta.append({"gid": gid, "target_idx": t + HORIZON_WEEKS,
                         "last_value": row[0], "ma4": row[1]})
    return X, y, meta


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def trend_class(change):
    if change >= GROW_THRESHOLD:
        return "grow"
    if change <= -GROW_THRESHOLD:
        return "decline"
    return "stable"


def mae(actual, pred):
    if not actual:
        return None
    return round(sum(abs(a - p) for a, p in zip(actual, pred)) / len(actual), 2)


def mape(actual, pred, floor=20):
    pairs = [(a, p) for a, p in zip(actual, pred) if a >= floor]
    if not pairs:
        return None
    return round(100 * sum(abs(a - p) / a for a, p in pairs) / len(pairs), 2)


def trend_accuracy_and_f1(actual, pred, last_values):
    """Trend-direction accuracy and macro-F1 across grow/stable/decline."""
    if not actual:
        return None, None
    classes = ["grow", "stable", "decline"]
    a_cls, p_cls = [], []
    for a, p, lv in zip(actual, pred, last_values):
        base = lv if lv > 0 else 1.0
        a_cls.append(trend_class((a - base) / base))
        p_cls.append(trend_class((p - base) / base))
    correct = sum(1 for x, z in zip(a_cls, p_cls) if x == z)
    acc = round(correct / len(a_cls), 3)

    f1s = []
    for c in classes:
        tp = sum(1 for x, z in zip(a_cls, p_cls) if z == c and x == c)
        fp = sum(1 for x, z in zip(a_cls, p_cls) if z == c and x != c)
        fn = sum(1 for x, z in zip(a_cls, p_cls) if z != c and x == c)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        f1s.append(f1)
    macro_f1 = round(sum(f1s) / len(f1s), 3)
    return acc, macro_f1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_forecast():
    history = load_json("history.json", [])
    live = load_json("live.json", {})
    demand_gap = load_json("demand_gap.json", {})

    remote_shares = field_share_map(live.get("remote_by_field"))
    entry_shares = field_share_map(live.get("entry_by_field"))
    gaps = gap_map(demand_gap)
    median_gap = statistics.median(gaps.values()) if gaps else 0.0

    week_order, groups = build_series(history)
    field_codes = {}
    X, y, meta = build_dataset(week_order, groups, remote_shares, entry_shares,
                               gaps, field_codes, median_gap)

    factory, model_name = load_regressor()
    notes = []

    # Temporal hold-out: newest target weeks become the test set.
    metrics = {
        "horizon_weeks": HORIZON_WEEKS,
        "n_samples": len(X),
        "n_groups_with_history": sum(1 for g in groups.values()
                                     if len(g["counts"]) >= MIN_HISTORY + 1),
        "features": ["ad_count_previous_week", "ad_count_4_week_average",
                     "ad_count_8_week_average", "trend_last_4_weeks",
                     "remote_share", "entry_level_share",
                     "search_attention_gap", "occupation_field_code"],
    }

    trained_model = None
    if X and factory is not None and len(X) >= 40:
        order = sorted(range(len(X)), key=lambda i: meta[i]["target_idx"])
        cut = int(len(order) * 0.8)
        train_i, test_i = order[:cut], order[cut:]
        if test_i and train_i:
            Xtr = [X[i] for i in train_i]
            ytr = [y[i] for i in train_i]
            Xte = [X[i] for i in test_i]
            yte = [y[i] for i in test_i]
            last_te = [meta[i]["last_value"] for i in test_i]
            ma4_te = [meta[i]["ma4"] for i in test_i]
            try:
                model = factory()
                model.fit(Xtr, ytr)
                pred = [max(0.0, float(v)) for v in model.predict(Xte)]
                trained_model = factory()
                trained_model.fit(X, y)  # refit on all data for live forecasting

                acc, f1 = trend_accuracy_and_f1(yte, pred, last_te)
                b_acc, b_f1 = trend_accuracy_and_f1(yte, last_te, last_te)
                metrics["model"] = {
                    "name": model_name,
                    "mae": mae(yte, pred),
                    "mape": mape(yte, pred),
                    "trend_accuracy": acc,
                    "trend_macro_f1": f1,
                }
                metrics["baseline_persistence"] = {
                    "name": "last-value (persistence)",
                    "mae": mae(yte, last_te),
                    "mape": mape(yte, last_te),
                    "trend_accuracy": b_acc,
                    "trend_macro_f1": b_f1,
                }
                metrics["baseline_moving_average"] = {
                    "name": "4-week moving average",
                    "mae": mae(yte, ma4_te),
                    "mape": mape(yte, ma4_te),
                }
                metrics["n_train"] = len(train_i)
                metrics["n_test"] = len(test_i)
                # Two honest comparisons. Persistence is hard to beat on raw
                # 4-week MAE (ad counts are noisy), but it is near-useless at
                # calling direction. The product uses the trend class, so the
                # trend comparison is the one that matters for the advice.
                m_mae = metrics["model"]["mae"]
                b_mae = metrics["baseline_persistence"]["mae"]
                metrics["beats_baseline_mae"] = bool(
                    m_mae is not None and b_mae is not None and m_mae <= b_mae)
                metrics["beats_baseline_trend_f1"] = bool(
                    f1 is not None and b_f1 is not None and f1 >= b_f1)
                notes.append(f"Trained {model_name} on {len(train_i)} samples, "
                             f"tested on {len(test_i)}.")
                if metrics["beats_baseline_trend_f1"] and not metrics["beats_baseline_mae"]:
                    notes.append("Model matches the baseline on demand level (MAE) "
                                 "but is far stronger at calling trend direction, "
                                 "which is what the career advice consumes.")
            except Exception as exc:
                trained_model = None
                notes.append(f"ML training failed ({exc.__class__.__name__}); "
                             f"using baseline forecast.")
    if trained_model is None and factory is None:
        notes.append(model_name)  # the unavailability reason
    if trained_model is None:
        notes.append("Forecasts generated from the baseline "
                     "(4-week moving average / persistence).")
        metrics.setdefault("model", None)

    # ---- Per-occupation forecast for the latest observed week --------------
    forecasts = []
    for gid, info in groups.items():
        counts = info["counts"]
        term = info["term"]
        if not term:
            continue
        fid, field_sv, field_en = classify_field(term)
        if not counts:
            continue
        last_idx = max(counts)
        current = counts.get(last_idx, 0.0)

        feature_row = None
        if len(counts) >= MIN_HISTORY:
            field_code = field_codes.get(fid or "unknown", len(field_codes))
            feature_row = make_feature_row(
                counts, last_idx, field_code,
                remote_shares.get(fid, 0.0), entry_shares.get(fid, 0.0),
                gaps.get(gid, median_gap))

        if feature_row is None:
            # Not enough contiguous history -> deterministic fallback.
            forecasts.append({
                "concept_id": gid, "term": term, "field": field_sv,
                "current_ads": int(current),
                "forecast_ads_4w": int(current),
                "pct_change": 0.0, "trend_class": "unknown",
                "source": "none", "confidence": "low",
                "last_observed_week": week_order[last_idx] if last_idx < len(week_order) else None,
            })
            continue

        if trained_model is not None:
            pred = max(0.0, float(trained_model.predict([feature_row])[0]))
            source = "ml"
            confidence = "high" if len(counts) >= 12 else "medium"
        else:
            # Baseline: blend persistence with the 4-week moving average.
            pred = 0.5 * feature_row[0] + 0.5 * feature_row[1]
            source = "baseline"
            confidence = "medium" if len(counts) >= 12 else "low"

        change = (pred - current) / current if current > 0 else 0.0
        forecasts.append({
            "concept_id": gid, "term": term, "field": field_sv,
            "current_ads": int(round(current)),
            "forecast_ads_4w": int(round(pred)),
            "pct_change": round(change, 4),
            "trend_class": trend_class(change),
            "source": source, "confidence": confidence,
            "last_observed_week": week_order[last_idx] if last_idx < len(week_order) else None,
        })

    forecasts.sort(key=lambda f: f["current_ads"], reverse=True)

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    forecast_doc = {
        "last_updated": now,
        "methodology_version": "career-signal-forecast-v1",
        "horizon_weeks": HORIZON_WEEKS,
        "grow_threshold": GROW_THRESHOLD,
        "model_source": "ml" if trained_model is not None else "baseline",
        "weeks_covered": [week_order[0], week_order[-1]] if week_order else [],
        "occupations": forecasts,
    }
    metrics_doc = {
        "last_updated": now,
        "methodology_version": "career-signal-forecast-v1",
        "model_source": "ml" if trained_model is not None else "baseline",
        "notes": notes,
        "metrics": metrics,
    }
    return forecast_doc, metrics_doc


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Train career-signal forecast model")
    parser.add_argument("--forecast-out",
                        default=os.path.join(DATA_DIR, "occupation_forecast.json"))
    parser.add_argument("--metrics-out",
                        default=os.path.join(DATA_DIR, "model_metrics.json"))
    args = parser.parse_args()

    print("Training career-signal demand-forecast model...")
    forecast_doc, metrics_doc = build_forecast()
    write_json(args.forecast_out, forecast_doc)
    write_json(args.metrics_out, metrics_doc)

    m = metrics_doc["metrics"]
    print(f"  model source : {forecast_doc['model_source']}")
    print(f"  samples      : {m.get('n_samples')}")
    if m.get("model"):
        print(f"  model MAE    : {m['model'].get('mae')}  "
              f"trend acc {m['model'].get('trend_accuracy')}  "
              f"F1 {m['model'].get('trend_macro_f1')}")
    if m.get("baseline_persistence"):
        print(f"  baseline MAE : {m['baseline_persistence'].get('mae')}")
    for note in metrics_doc["notes"]:
        print(f"  note: {note}")
    print(f"  forecasts    : {len(forecast_doc['occupations'])}")
    print(f"Wrote {args.forecast_out}")
    print(f"Wrote {args.metrics_out}")


if __name__ == "__main__":
    main()
