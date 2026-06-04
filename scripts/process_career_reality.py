#!/usr/bin/env python3
"""Generate data/career_reality.json for the Career Reality Check feature.

This script reads the existing static datasets and produces a single,
UI-ready model of career signals. It is intentionally deterministic and
transparent: every score comes from simple, explainable rules, not from a
black-box model. The goal is a blunt labour-market reality check, not a
prediction engine.

It reads (all optional, all handled gracefully if missing or sparse):
    data/live.json              current snapshot (ad counts, entry/remote by field)
    data/history.json           weekly snapshots, used for demand trend
    data/demand_gap.json        search attention vs demand -> crowding risk
    data/skill_velocity.json    skill momentum (growing / declining / stable)
    data/regional_split.json    regional specialisation per occupation field
    data/occupation_decay.json  long-range field demand (light context only)

It writes:
    data/career_reality.json

Run:
    python3 scripts/process_career_reality.py

This can later run unchanged as a Nebius Serverless AI Job (see nebius/README.md):
the inputs are plain JSON files and the output is a plain JSON artifact.

------------------------------------------------------------------------------
SCORING (career-reality-v1) — all rules are deliberately simple and documented
------------------------------------------------------------------------------
For every occupation we compute six signals and one combined opportunity score.

A. demand_level    high / medium / low        from current ad count (tertiles)
B. demand_trend    rising / stable / declining / unknown
                                                recent weeks vs earlier weeks
C. crowding_risk   high / medium / low / unknown
                                                from demand_gap search-vs-demand
D. entry_level_signal  strong / medium / weak / unknown
                                                field share of entry-level ads
E. remote_signal   strong / medium / weak / unknown
                                                field share of remote ads
F. skill momentum  (per related skill)         from skill_velocity growth
G. opportunity_score 0-100 (see compute_opportunity_score) combines all of A-F
   plus regional strength. It starts from demand and is nudged up or down by
   the other signals, then clamped to 0-100. It is explainable, not exact.
"""

import argparse
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")

METHODOLOGY_VERSION = "career-reality-v1"


# ---------------------------------------------------------------------------
# Robust IO helpers
# ---------------------------------------------------------------------------

def load_json(name, default=None):
    """Load data/<name>; never raise if the file is missing or invalid."""
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"  ! could not read {name} ({exc.__class__.__name__}); using fallback")
        return default if default is not None else {}


def as_list(value):
    return value if isinstance(value, list) else []


def lower(value):
    return str(value or "").lower()


# ---------------------------------------------------------------------------
# Occupation field classification
# ---------------------------------------------------------------------------
# Job ad data gives us granular occupation *groups* (e.g. "Mjukvaru- och
# systemutvecklare m.fl.") but the entry-level / remote / regional signals are
# only available per broad occupation *field* (e.g. "Data/IT"). We bridge the
# two with a transparent keyword map. Rules are checked in order; the first
# keyword that appears in the group name wins. Overlap-prone fields (social
# care before health, trades before generic engineering) come first on purpose.

FIELD_RULES = [
    ("GazW_2TU_kJw", "Yrken med social inriktning", "Social care", [
        "socialsekret", "socialpedagog", "behandlingsassist", "boendestöd",
        "personlig assistent", "personliga assistent", "vårdare", "fritidsled",
        "kurator", "diakon", "stödassistent", "stödpedagog",
    ]),
    ("NYW6_mP6_vwf", "Hälso- och sjukvård", "Healthcare", [
        "sjukskötersk", "läkare", "undersköter", "tandhygien", "tandläk",
        "fysioterap", "barnmorsk", "vårdbiträd", "ambulans", "röntgen",
        "psykolog", "farmaceut", "apotek",
    ]),
    ("MVqp_eS8_kDZ", "Pedagogik", "Education", [
        "lärare", "förskoll", "förskol", "pedagog", "rektor", "barnskötare",
        "studie- och yrkesväg", "speciallärare",
    ]),
    ("apaJ_2ja_LuF", "Data/IT", "Data / IT", [
        "utvecklare", "systemutveckl", "mjukvar", "it-säkerhet",
        "säkerhetsspecialist", "systemadministrat", "systemförvalt",
        "devops", "webb", "data scientist", "dataingenjör", "it-",
        "nätverkstekniker", "supporttekniker",
    ]),
    ("j7Cq_ZJe_GkT", "Bygg och anläggning", "Construction", [
        "bygg", "anläggning", "snickare", "murare", "betong", "takläggare",
        "anläggningsarbet", "ställningsbygg",
    ]),
    ("yhCP_AqT_tns", "Installation, drift, underhåll", "Install / maintenance", [
        "mekaniker", "fordonsreparat", "underhåll", "fastighetsskötare",
        "reparatör", "drifttekniker", "elektriker", "installation",
        "vvs", "servicetekniker",
    ]),
    ("wTEr_CBC_bqh", "Industriell tillverkning", "Manufacturing", [
        "maskinställare", "maskinoperatör", "industri", "tillverkning",
        "montör", "gjut", "svetsare", "processoperatör",
    ]),
    ("6Hq3_tKo_V57", "Yrken med teknisk inriktning", "Engineering / technical", [
        "civilingenjör", "ingenjör", "tekniker", "maskinteknik",
        "konstruktör", "arkitekt",
    ]),
    ("ASGV_zcE_bWf", "Transport, distribution, lager", "Transport / logistics", [
        "lastbilsför", "chaufför", "lager", "terminal", "transport",
        "distribut", "truckför", "budbil", "åkeri",
    ]),
    ("ScKy_FHB_7wT", "Hotell, restaurang, storhushåll", "Hospitality / food", [
        "kock", "servit", "hovmästare", "restaurang", "kallskänk",
        "köksbiträd", "bartender", "servering", "storhushåll", "barista",
    ]),
    ("RPTn_bxG_ExZ", "Försäljning, inköp, marknadsföring", "Sales / marketing", [
        "butikssälj", "säljare", "försäljning", "inköp", "marknadsför",
        "butik", "key account", "innesälj", "utesälj",
    ]),
    ("X82t_awd_Qyc", "Administration, ekonomi, juridik", "Admin / economy / legal", [
        "planerare", "utredare", "kundtjänst", "administrat", "ekonom",
        "redovisning", "jurist", "löne", "hr", "handläggare", "assistent",
        "controller", "sekreterare", "receptionist",
    ]),
    ("whao_Q6A_ScE", "Sanering och renhållning", "Cleaning / sanitation", [
        "städ", "renhållning", "sanering", "lokalvård",
    ]),
    ("E7hm_BLq_fqZ", "Säkerhet och bevakning", "Security", [
        "väktare", "bevakning", "ordningsvakt", "säkerhetsvakt",
    ]),
    ("9puE_nYg_crq", "Kultur, media, design", "Culture / media / design", [
        "design", "journalist", "media", "grafisk", "fotograf", "redaktör",
        "kommunikatör",
    ]),
    ("Uuf1_GMh_Uvw", "Kropps- och skönhetsvård", "Beauty / body care", [
        "frisör", "skönhet", "hudterapeut", "massör",
    ]),
    ("PaxQ_o1G_wWH", "Hantverk", "Crafts", [
        "hantverk", "guldsmed", "skräddare",
    ]),
    ("VuuL_7CH_adj", "Naturbruk", "Agriculture / nature", [
        "naturbruk", "lantbruk", "djurskötare", "trädgård", "skogs",
    ]),
    ("kJeN_wmw_9wX", "Naturvetenskapligt arbete", "Natural science", [
        "biolog", "kemist", "fysiker", "geolog", "laborant",
    ]),
    ("bH5L_uXD_ZAX", "Militära yrken", "Military", [
        "militär", "soldat", "officer",
    ]),
]

# English-facing field labels keyed by concept id (used for the consultant copy).
FIELD_EN = {fid: en for (fid, _sv, en, _kw) in FIELD_RULES}
FIELD_SV = {fid: sv for (fid, sv, _en, _kw) in FIELD_RULES}

# Field -> skill name fragments we treat as relevant for "skills to add".
# Matched (case-insensitive substring) against skill_velocity terms.
FIELD_SKILL_HINTS = {
    "apaJ_2ja_LuF": ["sql", "python", "java", "cloud", "azure", "aws", "linux",
                     "docker", "kubernetes", "javascript", ".net", "agila"],
    "X82t_awd_Qyc": ["excel", "sql", "redovisning", "lön", "bokföring",
                     "officepaket", "engelska", "ekonomi"],
    "RPTn_bxG_ExZ": ["crm", "försäljning", "key account", "förhandling",
                     "kundbemötande", "marknadsför"],
    "NYW6_mP6_vwf": ["omvårdnad", "journal", "läkemedel", "svensk legitimation",
                     "patient"],
    "GazW_2TU_kJw": ["socionom", "dokumentation", "bemötande", "lågaffektivt"],
    "MVqp_eS8_kDZ": ["pedagog", "lärarlegitimation", "didakt"],
    "ASGV_zcE_bWf": ["truckkort", "körkort", "lager", "ce-körkort", "adr"],
    "ScKy_FHB_7wT": ["kassavana", "servering", "livsmedelshygien", "matlagning"],
    "yhCP_AqT_tns": ["felsökning", "underhåll", "elinstallation", "körkort"],
    "wTEr_CBC_bqh": ["cnc", "svets", "ritningsläsning", "truckkort"],
    "j7Cq_ZJe_GkT": ["ritningsläsning", "byggvana", "ställning"],
    "6Hq3_tKo_V57": ["cad", "autocad", "projektledning", "ritningsläsning"],
}


def classify_field(term):
    """Return (field_id, field_sv, field_en) for an occupation group name."""
    text = lower(term)
    for fid, sv, en, keywords in FIELD_RULES:
        for kw in keywords:
            if kw in text:
                return fid, sv, en
    return None, None, None


# ---------------------------------------------------------------------------
# Signal builders
# ---------------------------------------------------------------------------

def build_field_rank_signal(entries, total_key="count"):
    """Turn a list of {concept_id, count} into a per-field strong/medium/weak map.

    Fields are ranked by their share of the total. Top third -> strong, middle
    -> medium, bottom -> weak. Fields absent from the list are 'weak' (they had
    no measurable presence in this signal).
    """
    rows = []
    total = 0
    for item in as_list(entries):
        count = float(item.get(total_key) or 0)
        if count <= 0:
            continue
        total += count
        rows.append((item.get("concept_id"), count))
    if not rows:
        return {}
    rows.sort(key=lambda r: r[1], reverse=True)
    n = len(rows)
    signal = {}
    for index, (fid, count) in enumerate(rows):
        if index < max(1, n // 3):
            level = "strong"
        elif index < max(2, (2 * n) // 3):
            level = "medium"
        else:
            level = "weak"
        signal[fid] = {"signal": level, "share": round(count / total, 4)}
    return signal


def build_trend_index(history):
    """Map occupation-group concept_id -> demand_trend using weekly history.

    We collect every available (week, count) point for a group, then compare the
    average of the more recent points with the average of the earlier points.
    Recent weeks in this dataset can be sparse (only the top groups are stored),
    so we work with whatever points exist and require at least four to judge.
    """
    weeks = as_list(history)
    series = {}  # concept_id -> list of (week, count) in chronological order
    for snapshot in weeks:
        week = snapshot.get("week")
        for group in as_list(snapshot.get("by_occupation_group")):
            cid = group.get("concept_id")
            if not cid:
                continue
            count = float(group.get("count") or 0)
            series.setdefault(cid, []).append((week, count))

    trend = {}
    for cid, points in series.items():
        counts = [c for _w, c in points if c > 0]
        if len(counts) < 4:
            trend[cid] = "unknown"
            continue
        half = len(counts) // 2
        earlier = counts[:half]
        recent = counts[half:]
        early_avg = sum(earlier) / len(earlier)
        recent_avg = sum(recent) / len(recent)
        if early_avg <= 0:
            trend[cid] = "unknown"
            continue
        change = (recent_avg - early_avg) / early_avg
        if change >= 0.08:
            trend[cid] = "rising"
        elif change <= -0.08:
            trend[cid] = "declining"
        else:
            trend[cid] = "stable"
    return trend


def build_skill_signals(skill_velocity):
    """Return (skills_list, lookup_by_lower_term) from skill_velocity.json.

    A skill's momentum signal is:
        growing   if 365d (or 90d) growth is clearly positive and it is not tiny
        declining if growth is clearly negative
        stable    otherwise
    We keep a noise floor so a handful of mentions cannot dominate.
    """
    skills_in = as_list(skill_velocity.get("skills"))
    out = []
    for skill in skills_in:
        latest = float(skill.get("latest_count") or 0)
        if latest < 8:  # noise floor
            continue
        g365 = skill.get("growth_365d")
        g90 = skill.get("growth_90d")
        g365 = float(g365) if isinstance(g365, (int, float)) else None
        g90 = float(g90) if isinstance(g90, (int, float)) else None
        primary = g365 if g365 is not None else g90
        if primary is None:
            signal = "stable"
        elif primary >= 15 and latest >= 12:
            signal = "growing"
        elif primary <= -20:
            signal = "declining"
        else:
            signal = "stable"
        out.append({
            "term": skill.get("term"),
            "concept_id": skill.get("concept_id"),
            "signal": signal,
            "latest_count": int(latest),
            "growth_90d": g90,
            "growth_365d": g365,
        })
    # Keep the most-mentioned skills so the file stays lean but useful.
    out.sort(key=lambda s: s["latest_count"], reverse=True)
    out = out[:180]
    lookup = {lower(s["term"]): s for s in out}
    return out, lookup


def build_regional_field_strength(regional_split):
    """Return {region_term: {field_id: {score, signal, vs_national}}}.

    A field is 'strong' in a region when that region runs well above the
    national share for the field (vs_national >= 1.15), 'medium' near the
    national mix, and 'weak' when clearly under-weighted.
    """
    out = {}
    for region in as_list(regional_split.get("regions")):
        term = region.get("term")
        if not term:
            continue
        field_map = {}
        for field in as_list(region.get("occupation_fields")):
            fid = field.get("concept_id")
            if not fid:
                continue
            vs = field.get("vs_national")
            vs = float(vs) if isinstance(vs, (int, float)) else 1.0
            if vs >= 1.3:
                score, signal = 88, "strong"
            elif vs >= 1.1:
                score, signal = 76, "strong"
            elif vs >= 0.85:
                score, signal = 62, "medium"
            elif vs >= 0.6:
                score, signal = 48, "weak"
            else:
                score, signal = 38, "weak"
            field_map[fid] = {"score": score, "signal": signal,
                              "vs_national": round(vs, 2)}
        if field_map:
            out[term] = field_map
    return out


# ---------------------------------------------------------------------------
# Opportunity score (G) — start from demand, nudge by every other signal
# ---------------------------------------------------------------------------

def compute_opportunity_score(demand_level, demand_trend, crowding_risk,
                              entry_signal, remote_signal, best_regional,
                              skill_momentum):
    """Return an explainable 0-100 opportunity score.

    Base is set by current demand. Each remaining signal adds or removes a few
    points. This is intentionally readable: you can reconstruct any score by
    hand from the occupation's signals.
    """
    base = {"high": 70, "medium": 50, "low": 30}.get(demand_level, 45)
    score = base

    score += {"rising": 8, "stable": 0, "declining": -8}.get(demand_trend, 0)
    score += {"low": 6, "medium": -2, "high": -8}.get(crowding_risk, 0)
    score += {"strong": 6, "medium": 0, "weak": -5}.get(entry_signal, 0)
    score += {"strong": 5, "medium": 2, "weak": 0}.get(remote_signal, 0)
    score += {"strong": 6, "medium": 3, "weak": 0}.get(best_regional, 0)
    score += {"growing": 5, "stable": 0, "declining": -4}.get(skill_momentum, 0)

    return max(0, min(100, round(score)))


# ---------------------------------------------------------------------------
# Consultant copy — blunt, practical, signal-driven (no soft filler)
# ---------------------------------------------------------------------------

def build_consultant_copy(field_en, demand_level, demand_trend, crowding_risk,
                          entry_signal, remote_signal):
    field = field_en or "this area"
    best_for = []
    caution = None

    if demand_level == "high" and crowding_risk == "high":
        summary = ("Strong, busy market, but competitive. Plenty of ads, plenty "
                   "of applicants. Better for people who can already show proof "
                   "than for complete beginners.")
        best_for.append("experienced")
    elif demand_level == "high":
        summary = ("Healthy demand and not overly crowded. A realistic target if "
                   "your profile is a reasonable fit.")
        best_for.append("realistic-now")
    elif demand_level == "medium" and crowding_risk == "high":
        summary = ("Moderate demand but high search attention. Expect competition "
                   "for a limited number of openings.")
    elif demand_level == "medium":
        summary = ("Moderate, steady demand. Worth targeting, but apply broadly "
                   "rather than to a single role.")
        best_for.append("realistic-now")
    else:
        summary = ("Thin current demand. Expect fewer openings and a longer "
                   "search. Treat it as a stretch target, not a first step.")

    if demand_trend == "rising":
        summary += " Demand has been rising in recent weeks."
    elif demand_trend == "declining":
        summary += " Demand has been softening in recent weeks."

    if entry_signal == "weak":
        caution = ("Entry-level access looks limited compared with total demand. "
                   "Beginners may need a nearby role first.")
    elif entry_signal == "strong":
        best_for.append("entry-friendly")

    if remote_signal in ("strong", "medium"):
        best_for.append("remote-friendly")

    return summary, best_for, caution


# ---------------------------------------------------------------------------
# Curated career paths (transparent templates, keyed to the form's experience
# areas). Roles reference real occupation groups in the data so they feel
# grounded. These give the UI a robust structural fallback for the three
# buckets even when free-text matching is weak.
# ---------------------------------------------------------------------------

def build_career_paths():
    return [
        {
            "path_id": "support_to_crm",
            "experience_key": "customer_service",
            "title": "Customer service → CRM / operations",
            "realistic_now_roles": [
                "Kundtjänstpersonal", "Support specialist", "Receptionist",
                "Administrativ assistent",
            ],
            "reachable_roles": [
                "CRM-koordinator", "Orderkoordinator", "Operations coordinator",
                "Rapporteringsassistent",
            ],
            "risky_roles": [
                "Data scientist", "IT-säkerhetsspecialister", "Senior analytiker",
            ],
            "skills_to_add": [
                "Excel pivottabeller", "CRM-rapportering", "SQL grunder",
                "Svenskt arbetsplatsspråk i skrift",
            ],
            "search_keywords": {
                "sv": ["kundtjänst", "kundsupport", "ordermottagare", "CRM-koordinator"],
                "en": ["customer support", "CRM coordinator", "operations coordinator"],
            },
            "reasoning": ("Customer service experience transfers cleanly into "
                          "coordination and CRM roles. Move toward reporting and "
                          "data step by step instead of jumping straight to analyst titles."),
        },
        {
            "path_id": "sales_to_marketing_automation",
            "experience_key": "sales",
            "title": "Sales → account management / marketing automation",
            "realistic_now_roles": [
                "Innesäljare", "Butikssäljare, dagligvaror", "Account coordinator",
                "Kundansvarig (junior)",
            ],
            "reachable_roles": [
                "Key account manager", "Marketing automation assistant",
                "CRM-koordinator",
            ],
            "risky_roles": [
                "Marknadschef", "Data scientist", "Senior growth lead",
            ],
            "skills_to_add": [
                "CRM (t.ex. HubSpot/Salesforce)", "Excel", "Förhandling",
                "Engelska i affärssammanhang",
            ],
            "search_keywords": {
                "sv": ["innesäljare", "account manager", "kundansvarig", "B2B-säljare"],
                "en": ["account manager", "sales coordinator", "marketing automation"],
            },
            "reasoning": ("Sales experience is in steady demand. Add structured "
                          "tools (CRM, reporting) to move from selling into account "
                          "management and marketing operations."),
        },
        {
            "path_id": "admin_to_reporting",
            "experience_key": "admin",
            "title": "Admin → reporting / operations / data",
            "realistic_now_roles": [
                "Administrativ assistent", "Planerare och utredare m.fl.",
                "Ekonomiassistent", "Orderadministratör",
            ],
            "reachable_roles": [
                "Rapporteringsassistent", "Operations coordinator",
                "Junior controller", "Verksamhetsutvecklare (junior)",
            ],
            "risky_roles": [
                "Data scientist", "Senior analytiker", "Business intelligence-specialist",
            ],
            "skills_to_add": [
                "SQL grunder", "Excel pivottabeller", "Power BI",
                "Processdokumentation",
            ],
            "search_keywords": {
                "sv": ["administratör", "ekonomiassistent", "rapportering", "koordinator"],
                "en": ["operations coordinator", "reporting assistant", "junior analyst"],
            },
            "reasoning": ("Admin experience is the most flexible base. Reporting "
                          "and operations roles are reachable with Excel and basic "
                          "SQL; full analyst roles come later, not first."),
        },
        {
            "path_id": "it_specialist_tracks",
            "experience_key": "it",
            "title": "IT / tech → specialist tracks",
            "realistic_now_roles": [
                "Supporttekniker", "Systemadministratör (junior)",
                "Testare", "IT-koordinator",
            ],
            "reachable_roles": [
                "Mjukvaru- och systemutvecklare m.fl.", "DevOps (junior)",
                "Dataingenjör (junior)",
            ],
            "risky_roles": [
                "IT-säkerhetsspecialister", "Senior arkitekt", "Data scientist",
            ],
            "skills_to_add": [
                "SQL", "Python", "Git", "Molnplattform (Azure/AWS)",
            ],
            "search_keywords": {
                "sv": ["supporttekniker", "systemutvecklare", "testare", "DevOps"],
                "en": ["IT support", "software developer", "QA engineer", "DevOps"],
            },
            "reasoning": ("IT demand is strong but the senior and security tracks "
                          "are crowded. Enter through support, test, or junior "
                          "developer roles and specialise from there."),
        },
        {
            "path_id": "healthcare_assistant_to_care",
            "experience_key": "healthcare",
            "title": "Healthcare → care / nursing track",
            "realistic_now_roles": [
                "Undersköterskor, hemtjänst, hemsjukvård, äldreboende och habilitering",
                "Vårdbiträde", "Personliga assistenter",
            ],
            "reachable_roles": [
                "Specialistundersköterska", "Vårdkoordinator",
            ],
            "risky_roles": [
                "Grundutbildade sjuksköterskor (utan legitimation)",
                "Specialistläkare",
            ],
            "skills_to_add": [
                "Undersköterskeutbildning", "Svensk vårddokumentation",
                "Läkemedelshantering (delegering)",
            ],
            "search_keywords": {
                "sv": ["undersköterska", "vårdbiträde", "hemtjänst", "personlig assistent"],
                "en": ["assistant nurse", "care assistant", "personal assistant"],
            },
            "reasoning": ("Care demand is high and entry-friendly. Licensed nurse "
                          "and doctor roles require Swedish credentials, so treat "
                          "them as study targets, not immediate applications."),
        },
        {
            "path_id": "education_track",
            "experience_key": "education",
            "title": "Education → teaching / pedagogy",
            "realistic_now_roles": [
                "Barnskötare", "Elevassistent", "Vikarie (skola/förskola)",
            ],
            "reachable_roles": [
                "Fritidsledare m.fl.", "Lärarassistent",
            ],
            "risky_roles": [
                "Grundskollärare (utan legitimation)", "Gymnasielärare (utan legitimation)",
            ],
            "skills_to_add": [
                "Lärarlegitimation / pedagogisk utbildning", "Svenska C1",
                "Ledarskap i klassrum",
            ],
            "search_keywords": {
                "sv": ["barnskötare", "elevassistent", "vikarie skola", "fritidsledare"],
                "en": ["teaching assistant", "after-school leader", "substitute teacher"],
            },
            "reasoning": ("Assistant and substitute roles are reachable now. "
                          "Qualified teacher roles need a Swedish teaching licence, "
                          "so plan study before targeting them."),
        },
        {
            "path_id": "restaurant_to_hospitality",
            "experience_key": "restaurant",
            "title": "Restaurant / service → hospitality coordination",
            "realistic_now_roles": [
                "Restaurang- och köksbiträden m.fl.", "Hovmästare och servitörer",
                "Barista", "Butikssäljare, dagligvaror",
            ],
            "reachable_roles": [
                "Skiftledare", "Restaurangbiträde med kassaansvar",
                "Kundvärd / customer success (junior)",
            ],
            "risky_roles": [
                "Restaurangchef", "Kockar och kallskänkor (utan utbildning)",
            ],
            "skills_to_add": [
                "Kassasystem", "Livsmedelshygien", "Svenskt kundbemötande",
                "Schemaläggning",
            ],
            "search_keywords": {
                "sv": ["serveringspersonal", "köksbiträde", "kassapersonal", "kundvärd"],
                "en": ["waiter", "kitchen assistant", "barista", "customer host"],
            },
            "reasoning": ("Service experience transfers into any customer-facing "
                          "role. Use it to move toward coordination and customer "
                          "success rather than chasing chef or manager titles first."),
        },
        {
            "path_id": "logistics_to_operations",
            "experience_key": "logistics",
            "title": "Logistics / warehouse → operations / supply coordination",
            "realistic_now_roles": [
                "Lager- och terminalpersonal", "Lastbilsförare m.fl.",
                "Truckförare", "Orderplockare",
            ],
            "reachable_roles": [
                "Lagerkoordinator", "Logistikkoordinator", "Operations coordinator",
            ],
            "risky_roles": [
                "Logistikchef", "Supply chain analyst (senior)",
            ],
            "skills_to_add": [
                "Truckkort", "Excel", "WMS / lagersystem", "CE-körkort",
            ],
            "search_keywords": {
                "sv": ["lagerarbetare", "truckförare", "logistikkoordinator", "orderplock"],
                "en": ["warehouse worker", "forklift driver", "logistics coordinator"],
            },
            "reasoning": ("Warehouse and transport roles are widely available now. "
                          "Add a forklift licence and Excel to move into coordination "
                          "and planning roles."),
        },
        {
            "path_id": "no_experience_entry",
            "experience_key": "none",
            "title": "No clear experience → entry-friendly roles",
            "realistic_now_roles": [
                "Restaurang- och köksbiträden m.fl.", "Städare",
                "Lager- och terminalpersonal", "Butikssäljare, dagligvaror",
                "Personliga assistenter",
            ],
            "reachable_roles": [
                "Kundtjänstpersonal", "Administrativ assistent",
            ],
            "risky_roles": [
                "Mjukvaru- och systemutvecklare m.fl.", "Specialistläkare",
            ],
            "skills_to_add": [
                "Svenska (SFI/grundläggande)", "Truckkort", "Kassavana",
                "CV på svenska och engelska",
            ],
            "search_keywords": {
                "sv": ["lagerarbetare", "köksbiträde", "städ", "butik", "personlig assistent"],
                "en": ["warehouse", "kitchen assistant", "cleaning", "retail assistant"],
            },
            "reasoning": ("Start with roles that have strong entry-level access and "
                          "high volume. Build a track record, then move toward "
                          "coordination or specialist routes with study."),
        },
    ]


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

FORECAST_TREND_TO_DEMAND = {
    "grow": "rising",
    "stable": "stable",
    "decline": "declining",
}


def build_forecast_lookup(forecast_doc):
    """Map occupation concept_id -> forecast record from occupation_forecast.json."""
    lookup = {}
    for occ in as_list(forecast_doc.get("occupations")):
        cid = occ.get("concept_id")
        if cid:
            lookup[cid] = occ
    return lookup


def build_career_reality():
    live = load_json("live.json", {})
    history = load_json("history.json", [])
    demand_gap = load_json("demand_gap.json", {})
    skill_velocity = load_json("skill_velocity.json", {})
    regional_split = load_json("regional_split.json", {})
    # ML forecast is OPTIONAL. If train_career_signal_model.py has not run (or
    # produced no artifact), we silently fall back to history/rule-based trend.
    forecast_doc = load_json("occupation_forecast.json", {})
    forecast_lookup = build_forecast_lookup(forecast_doc)
    forecast_model_source = forecast_doc.get("model_source")  # "ml" | "baseline" | None

    # Field-level signals.
    entry_signal_map = build_field_rank_signal(live.get("entry_by_field"))
    remote_signal_map = build_field_rank_signal(live.get("remote_by_field"))
    trend_map = build_trend_index(history)
    skills_list, skill_lookup = build_skill_signals(skill_velocity)
    regional_field_strength = build_regional_field_strength(regional_split)

    # Current ad count per occupation group, preferring the live snapshot.
    live_group_count = {}
    for group in as_list(live.get("by_occupation_group")):
        cid = group.get("concept_id")
        if cid:
            live_group_count[cid] = int(group.get("count") or 0)

    # Assemble the occupation universe: demand_gap groups (rich crowding signal)
    # plus any live groups not already represented.
    raw_groups = {}  # concept_id -> {term, ad_count, search_count, crowd_signal}
    for occ in as_list(demand_gap.get("occupations")):
        cid = occ.get("concept_id")
        if not cid:
            continue
        raw_groups[cid] = {
            "term": occ.get("term"),
            "ad_count": int(occ.get("ad_count") or 0),
            "search_count": occ.get("search_count"),
            "crowd_signal": occ.get("signal"),
        }
    for group in as_list(live.get("by_occupation_group")):
        cid = group.get("concept_id")
        if cid and cid not in raw_groups:
            raw_groups[cid] = {
                "term": group.get("term"),
                "ad_count": int(group.get("count") or 0),
                "search_count": None,
                "crowd_signal": None,
            }

    # Demand-level tertiles across the whole occupation universe (transparent).
    ad_counts = sorted(
        (live_group_count.get(cid, info["ad_count"]) for cid, info in raw_groups.items()),
        reverse=True,
    )
    n = len(ad_counts) or 1
    high_cut = ad_counts[min(n - 1, max(0, n // 3 - 1))] if ad_counts else 0
    low_cut = ad_counts[min(n - 1, (2 * n) // 3)] if ad_counts else 0

    def demand_level_for(count):
        if count >= high_cut and count > 0:
            return "high"
        if count >= low_cut:
            return "medium"
        return "low"

    # Map regional strength field -> ordered list of strong/medium regions.
    field_region_rows = {}  # field_id -> [(region_term, score, signal)]
    for region_term, field_map in regional_field_strength.items():
        for fid, info in field_map.items():
            field_region_rows.setdefault(fid, []).append(
                (region_term, info["score"], info["signal"]))
    for fid in field_region_rows:
        field_region_rows[fid].sort(key=lambda r: r[1], reverse=True)

    occupations = []
    for cid, info in raw_groups.items():
        term = info["term"]
        if not term:
            continue
        fid, field_sv, field_en = classify_field(term)
        current_ads = live_group_count.get(cid, info["ad_count"])

        demand_level = demand_level_for(current_ads)

        crowd = info.get("crowd_signal")
        if crowd == "high_attention_low_demand":
            crowding_risk = "high"
        elif crowd:
            crowding_risk = "medium"
        else:
            crowding_risk = "unknown"

        # Demand trend: prefer the ML/baseline forecast, fall back to the
        # history-derived trend, then to "unknown". This is the "ML where
        # available, deterministic fallback otherwise" rule.
        forecast = forecast_lookup.get(cid)
        forecast_block = None
        if forecast and forecast.get("trend_class") in FORECAST_TREND_TO_DEMAND:
            demand_trend = FORECAST_TREND_TO_DEMAND[forecast["trend_class"]]
            trend_source = forecast.get("source", "baseline")
            forecast_block = {
                "forecast_ads_4w": forecast.get("forecast_ads_4w"),
                "pct_change": forecast.get("pct_change"),
                "trend_class": forecast.get("trend_class"),
                "horizon_weeks": forecast_doc.get("horizon_weeks", 4),
                "source": trend_source,
                "confidence": forecast.get("confidence"),
            }
        else:
            demand_trend = trend_map.get(cid, "unknown")
            trend_source = "history" if demand_trend != "unknown" else "none"

        entry_signal = entry_signal_map.get(fid, {}).get("signal", "unknown") if fid else "unknown"
        remote_signal = remote_signal_map.get(fid, {}).get("signal", "unknown") if fid else "unknown"

        # Regional strength: top regions for this field.
        regional_strength = []
        best_regional = "weak"
        if fid and fid in field_region_rows:
            for region_term, score, signal in field_region_rows[fid][:6]:
                regional_strength.append({
                    "region": region_term, "score": score, "signal": signal,
                })
            if regional_strength:
                top_signal = regional_strength[0]["signal"]
                best_regional = top_signal

        # Related skills for this field, with momentum from skill_velocity.
        related_skills = []
        skill_momentum = "unknown"
        growing = stable = declining = 0
        for fragment in FIELD_SKILL_HINTS.get(fid, [])[:8]:
            match = None
            for term_l, skill in skill_lookup.items():
                if fragment in term_l:
                    match = skill
                    break
            if match:
                related_skills.append({"skill": match["term"], "signal": match["signal"]})
                if match["signal"] == "growing":
                    growing += 1
                elif match["signal"] == "declining":
                    declining += 1
                else:
                    stable += 1
            else:
                related_skills.append({"skill": fragment, "signal": "unknown"})
            if len(related_skills) >= 5:
                break
        if growing or declining or stable:
            if growing >= max(1, declining + 1):
                skill_momentum = "growing"
            elif declining > growing:
                skill_momentum = "declining"
            else:
                skill_momentum = "stable"

        opportunity_score = compute_opportunity_score(
            demand_level, demand_trend, crowding_risk, entry_signal,
            remote_signal, best_regional, skill_momentum)

        summary, best_for, caution = build_consultant_copy(
            field_en, demand_level, demand_trend, crowding_risk,
            entry_signal, remote_signal)

        occupations.append({
            "concept_id": cid,
            "term": term,
            "field": field_sv,
            "field_id": fid,
            "field_label": field_en,
            "current_ads": current_ads,
            "current_positions": None,
            "search_count": info.get("search_count"),
            "demand_level": demand_level,
            "demand_trend": demand_trend,
            "trend_source": trend_source,
            "forecast": forecast_block,
            "opportunity_score": opportunity_score,
            "crowding_risk": crowding_risk,
            "entry_level_signal": entry_signal,
            "remote_signal": remote_signal,
            "skill_momentum": skill_momentum,
            "regional_strength": regional_strength,
            "related_skills": related_skills,
            "consultant_summary": summary,
            "best_for": best_for,
            "caution": caution,
        })

    occupations.sort(key=lambda o: o["opportunity_score"], reverse=True)

    regions = []
    for region in as_list(regional_split.get("regions")):
        term = region.get("term")
        if term:
            regions.append({"concept_id": region.get("concept_id"), "term": term})
    if not regions:  # fallback to live regions
        for region in as_list(live.get("by_region")):
            term = region.get("term")
            if term:
                regions.append({"concept_id": region.get("concept_id"), "term": term})

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "last_updated": now,
        "methodology_version": METHODOLOGY_VERSION,
        "forecast_model_source": forecast_model_source,  # "ml" | "baseline" | None
        "sources": {
            "live_week": live.get("week"),
            "demand_gap_week": demand_gap.get("week"),
            "regional_split_week": regional_split.get("week"),
            "skill_velocity_updated": skill_velocity.get("last_updated"),
            "forecast_updated": forecast_doc.get("last_updated"),
        },
        "regions": regions,
        "regional_field_strength": regional_field_strength,
        "skills": skills_list,
        "occupations": occupations,
        "career_paths": build_career_paths(),
    }


def build_opportunity_scores(career_reality):
    """Compact occupation x region signal table (the artifact a /career-signal
    endpoint would return). Combines the ML/rule opportunity score with the
    regional specialisation weight for every occupation/region pair."""
    rfs = career_reality.get("regional_field_strength", {})
    rows = []
    for occ in career_reality.get("occupations", []):
        base = occ["opportunity_score"]
        fid = occ.get("field_id")
        regional_scores = {}
        for region_term, field_map in rfs.items():
            info = field_map.get(fid) if fid else None
            if not info:
                continue
            # Nudge the national score toward the region's specialisation.
            delta = {"strong": 6, "medium": 0, "weak": -6}.get(info["signal"], 0)
            regional_scores[region_term] = max(0, min(100, base + delta))
        rows.append({
            "concept_id": occ["concept_id"],
            "term": occ["term"],
            "field": occ.get("field"),
            "demand_level": occ["demand_level"],
            "demand_trend": occ["demand_trend"],
            "trend_source": occ.get("trend_source"),
            "opportunity_score": base,
            "forecast": occ.get("forecast"),
            "regional_scores": regional_scores,
        })
    rows.sort(key=lambda r: r["opportunity_score"], reverse=True)
    return {
        "last_updated": career_reality["last_updated"],
        "methodology_version": METHODOLOGY_VERSION,
        "forecast_model_source": career_reality.get("forecast_model_source"),
        "occupations": rows,
    }


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Generate Career Reality Check artifacts")
    parser.add_argument("--out", default=os.path.join(DATA_DIR, "career_reality.json"),
                        help="Output path (default: data/career_reality.json)")
    parser.add_argument("--scores-out",
                        default=os.path.join(DATA_DIR, "opportunity_scores.json"),
                        help="Compact occupation x region score table")
    args = parser.parse_args()

    print("Building Career Reality Check model...")
    payload = build_career_reality()
    write_json(args.out, payload)

    scores = build_opportunity_scores(payload)
    write_json(args.scores_out, scores)

    src = payload.get("forecast_model_source") or "none (rule-based fallback)"
    print(f"  occupations:   {len(payload['occupations'])}")
    print(f"  skills:        {len(payload['skills'])}")
    print(f"  regions:       {len(payload['regions'])}")
    print(f"  career paths:  {len(payload['career_paths'])}")
    print(f"  forecast model:{src}")
    print(f"Wrote {args.out}")
    print(f"Wrote {args.scores_out}")


if __name__ == "__main__":
    main()
