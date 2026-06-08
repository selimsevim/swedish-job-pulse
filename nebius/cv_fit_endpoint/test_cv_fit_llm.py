from cv_fit_llm import _parse_and_ground


EVIDENCE = {
    "best_fit_roles": ["Logistics Coordinator", "Warehouse Worker"],
    "adjacent_roles": ["Truck Driver"],
    "off_lane_roles": [],
    "missing_skills": ["Reporting"],
    "market_signal": "Rising demand · high crowding · medium regional fit",
    "region": "Stockholms län",
    "regional_outlook": {
        "selected_region": {
            "region": "Stockholms län",
            "local_market": "strong",
        }
    },
}


bad = (
    '{"main_answer":"Search in Stockholms län for mid-seniority logistics roles.",'
    '"why_recommendation":["Good fit.","Demand is rising.","Stockholm is strong."]}'
)
assert _parse_and_ground(bad, EVIDENCE) is None

generic = (
    '{"main_answer":"Focus on logistics roles.",'
    '"why_recommendation":["Good fit.","Demand is rising.","Stockholm is strong."]}'
)
assert _parse_and_ground(generic, EVIDENCE) is None

wrong_market = (
    '{"main_answer":"Prioritise Logistics Coordinator because Stockholm has a strong local market.",'
    '"why_recommendation":["Good fit.","Demand has moderate crowding.","Consider remote work."]}'
)
assert _parse_and_ground(wrong_market, EVIDENCE) is None

useful = (
    '{"main_answer":"Prioritise Logistics Coordinator roles; rising demand helps, '
    'but high crowding makes reporting evidence important.",'
    '"why_recommendation":["Your planning experience supports Logistics Coordinator roles.",'
    '"Demand is rising, but competition remains high.",'
    '"Stockholms län is the strongest regional market for this field."]}'
)
parsed = _parse_and_ground(useful, EVIDENCE)
assert parsed is not None
assert parsed["main_answer"].startswith("Prioritise Logistics Coordinator")

print("OK - generic regional headlines rejected; useful role decision accepted.")
