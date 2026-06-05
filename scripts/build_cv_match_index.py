#!/usr/bin/env python3
"""Build the CV-to-Market Fit engine index and evaluate it on synthetic CVs.

This is the reproducible, NO-PERSONAL-DATA layer behind the CV Job Fit Scanner.
The live website parses an uploaded PDF entirely in the browser (nothing is
uploaded or stored); this script never touches a real CV. It builds the role
ontology + retrieval index and proves matcher quality on synthetic CVs.

The engine has four layers (see nebius/README.md for the Nebius mapping):

  1. CV understanding   -> structured career identity (domain, seniority, tools)
  2. Embedding retrieval -> match CV meaning to a rich role ontology
  3. Job-fit ranking     -> rerank roles by semantic + skill + domain + seniority
  4. Explanation         -> turn evidence into a readable report (in app.js)

EMBEDDING LAYER — important honesty note
    A static website cannot run a neural embedding model (BGE-M3 / Qwen3) in the
    browser to embed the CV query at request time, and this environment has no
    torch. So the SHIPPED retrieval uses a transparent, reproducible MULTILINGUAL
    TF-IDF VECTOR SPACE over a synonym/domain-expanded role ontology
    (SFMC == Salesforce Marketing Cloud == Martech). Role vectors are built here;
    the browser builds the CV query vector with the SAME tokenizer + shipped IDF
    and ranks by cosine. The architecture is drop-in for a real multilingual
    embedding model: a Nebius job swaps build_role_vectors()/embed_query() for
    BGE-M3 or Qwen3-Embedding and the cosine-ranking contract is unchanged.

Outputs (all committed, all synthetic / public-data derived):
  data/cv_match_index.json   role ontology + skill vocab + IDF + role vectors
  data/sample_cvs.json       synthetic, fictional CV texts for the demo
  data/cv_match_metrics.json retrieval + ranking metrics over synthetic CVs

Run:
  python3 scripts/build_cv_match_index.py

Standard library only.
"""

import argparse
import datetime as dt
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")

INDEX_VERSION = "cv-fit-engine-v2"

# ---------------------------------------------------------------------------
# Synonym / domain canonicalisation. Applied (longest phrase first) to lower-
# cased text before tokenisation, in BOTH role docs and CV text, so that
# domain-equivalent surface forms collapse to one token. This is the practical
# fix for "SFMC consultant" getting flattened into "digital marketing".
#
# SCALABILITY NOTE — this hand-written list is a BOOTSTRAP, not the strategy.
# It is deliberately small and cannot cover every abbreviation. The scalable
# replacements (see nebius/README.md) are:
#   1. Neural embeddings (BGE-M3 / Qwen3) at the /cv-fit endpoint, which place
#      "SFMC" and "Salesforce Marketing Cloud" near each other with NO synonym
#      list at all — abbreviation handling is learned, not enumerated.
#   2. An optional offline LLM "alias expansion" Nebius job that auto-generates
#      these clusters from the role/skill vocabulary and commits them as data,
#      so the static fallback stays reproducible without anyone hand-typing.
# Runtime online search is intentionally avoided: it breaks reproducibility,
# determinism and the static-first / no-secrets constraints of the challenge.
# ---------------------------------------------------------------------------
SYNONYMS = [
    ("salesforce marketing cloud", " sfmc "),
    ("marketing cloud", " sfmc "),
    ("salesforce data cloud", " data_cloud "),
    ("data cloud", " data_cloud "),
    ("journey builder", " sfmc journeys "),
    ("email studio", " sfmc email "),
    ("marketing automation", " marketing_automation "),
    ("martech", " martech marketing_automation "),
    ("solution architect", " solution_architect architecture "),
    ("integration specialist", " integration "),
    ("api integration", " integration apis "),
    ("system integration", " integration "),
    ("middleware", " integration "),
    ("rest api", " rest apis "),
    ("restful", " rest apis "),
    ("power bi", " power_bi "),
    ("business intelligence", " bi "),
    ("data analyst", " data_analyst analytics "),
    ("machine learning", " machine_learning "),
    ("ci/cd", " cicd "),
    ("customer relationship management", " crm "),
    ("key account", " account_management "),
    ("account management", " account_management "),
    ("search engine optimization", " seo "),
    ("search engine optimisation", " seo "),
    ("social media", " social_media "),
    ("content marketing", " content "),
    ("supply chain", " supply_chain logistics "),
    ("driving license", " driving_license "),
    ("driver's license", " driving_license "),
    ("ce license", " ce_license driving_license "),
    ("patient care", " patient_care care "),
    ("elderly care", " elderly_care care "),
]

STOPWORDS = set("""
a an the and or of to in for on with as at is are be by from this that your you
i we our work worked working experience years year ett en och for med av i pa som ar
de det en man har inte jag vi
""".split())

TOKEN_RE = re.compile(r"[a-z0-9_+#]+")


def canon(text):
    low = " " + str(text or "").lower() + " "
    for phrase, repl in SYNONYMS:
        low = low.replace(phrase, repl)
    return low


def tokenize(text):
    return [t for t in TOKEN_RE.findall(canon(text))
            if len(t) >= 2 and t not in STOPWORDS]


def tf_weights(tokens):
    counts = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return {t: 1.0 + math.log(c) for t, c in counts.items()}


# ---------------------------------------------------------------------------
# Role ontology. Each role carries the domain (for guardrails), the public
# occupation field (for live market signals), seniority, defining skills, and a
# rich "doc" of terms used to build its retrieval vector.
# ---------------------------------------------------------------------------
FIELDS = {
    "crm_martech": ("RPTn_bxG_ExZ", "Sales / marketing"),
    "digital_marketing": ("RPTn_bxG_ExZ", "Sales / marketing"),
    "sales": ("RPTn_bxG_ExZ", "Sales / marketing"),
    "data_analytics": ("apaJ_2ja_LuF", "Data / IT"),
    "software": ("apaJ_2ja_LuF", "Data / IT"),
    "admin_ops": ("X82t_awd_Qyc", "Admin / economy / legal"),
    "healthcare": ("NYW6_mP6_vwf", "Healthcare"),
    "logistics": ("ASGV_zcE_bWf", "Transport / logistics"),
    "education": ("MVqp_eS8_kDZ", "Education"),
    "hospitality": ("ScKy_FHB_7wT", "Hospitality / food"),
}

# Domain adjacency (for bucketing into adjacent vs not-your-lane). Asymmetric on
# purpose: a CRM/martech technical profile treats SEO/social as off-lane.
DOMAIN_ADJACENCY = {
    "crm_martech": {"data_analytics", "admin_ops", "sales", "software"},
    "data_analytics": {"crm_martech", "admin_ops", "software"},
    "software": {"data_analytics", "crm_martech"},
    "admin_ops": {"crm_martech", "data_analytics", "sales"},
    "sales": {"crm_martech", "admin_ops"},
    "digital_marketing": {"crm_martech", "sales"},
    "healthcare": set(),
    "logistics": {"admin_ops"},
    "education": set(),
    "hospitality": {"sales"},
}

DOMAIN_LABEL = {
    "crm_martech": "CRM / marketing automation", "digital_marketing": "digital marketing",
    "sales": "sales", "data_analytics": "analytics / BI", "software": "software / IT",
    "admin_ops": "admin / operations", "healthcare": "healthcare",
    "logistics": "logistics", "education": "education", "hospitality": "hospitality",
}


def role(rid, title, domain, seniority, req, nice=None, lang=False,
         aliases=None, kw=None, terms=None, secondary=None):
    field_id, field_label = FIELDS[domain]
    return {
        "role_id": rid, "title": title, "domain": domain,
        "secondary_domains": secondary or [],
        "field_id": field_id, "field_label": field_label,
        "seniority": seniority, "required_skills": req, "nice_skills": nice or [],
        "language_sensitive": lang,
        "aliases": aliases or [title.lower()],
        "search_keywords": kw or [title],
        "terms": terms or [],
    }


def build_catalog():
    return [
        # --- CRM / martech technical cluster --------------------------------
        role("sfmc_consultant", "Salesforce Marketing Cloud Consultant", "crm_martech", "mid",
             ["sfmc", "marketing_automation", "crm", "sql"],
             ["ampscript", "ssjs", "rest", "soap", "integration"],
             aliases=["sfmc", "salesforce marketing cloud", "marketing cloud consultant", "sfmc consultant"],
             kw=["SFMC Consultant", "Salesforce Marketing Cloud"],
             terms=["sfmc", "ampscript", "ssjs", "journeys", "email", "crm", "consultant", "martech"]),
        role("ma_techlead", "Marketing Automation Tech Lead", "crm_martech", "senior",
             ["marketing_automation", "sfmc", "crm", "leadership"],
             ["integration", "sql", "architecture"],
             aliases=["marketing automation tech lead", "martech lead", "marketing automation lead"],
             kw=["Marketing Automation Tech Lead"],
             terms=["marketing_automation", "sfmc", "lead", "team", "architecture", "martech"]),
        role("martech_consultant", "Martech Consultant", "crm_martech", "mid",
             ["marketing_automation", "crm", "integration"],
             ["sfmc", "sql", "apis"],
             aliases=["martech consultant", "marketing technology consultant"],
             kw=["Martech Consultant", "Marketing Technology Consultant"],
             terms=["martech", "marketing_automation", "consultant", "crm", "integration", "platform"]),
        role("crm_tech_consultant", "CRM Technical Consultant", "crm_martech", "mid",
             ["crm", "sql", "integration"],
             ["sfmc", "apis", "marketing_automation"],
             aliases=["crm technical consultant", "crm consultant", "crm developer"],
             kw=["CRM Technical Consultant", "CRM Consultant"],
             terms=["crm", "technical", "consultant", "integration", "sql", "salesforce"]),
        role("integration_specialist", "Integration Specialist", "crm_martech", "mid",
             ["integration", "apis", "rest"],
             ["soap", "sql", "cloud", "python"],
             secondary=["software"],
             aliases=["integration specialist", "integration engineer", "integration developer"],
             kw=["Integration Specialist", "API Integration"],
             terms=["integration", "apis", "rest", "soap", "middleware", "systems", "data"]),
        role("solution_architect_martech", "Solution Architect, Marketing Technology", "crm_martech", "senior",
             ["architecture", "marketing_automation", "integration", "crm"],
             ["sfmc", "cloud", "apis", "leadership"],
             secondary=["software"],
             aliases=["solution architect", "martech architect", "marketing technology architect"],
             kw=["Solution Architect Marketing Technology", "Martech Architect"],
             terms=["solution_architect", "architecture", "martech", "integration", "cloud", "design"]),
        role("marketing_ops_engineer", "Marketing Operations Engineer", "crm_martech", "mid",
             ["marketing_automation", "sql", "integration"],
             ["sfmc", "apis", "analytics"],
             secondary=["data_analytics"],
             aliases=["marketing operations engineer", "marketing ops", "marketing operations"],
             kw=["Marketing Operations Engineer", "Marketing Ops"],
             terms=["marketing", "operations", "automation", "data", "campaign", "engineer"]),
        role("data_integration_specialist", "Data Integration Specialist", "crm_martech", "mid",
             ["integration", "sql", "apis"],
             ["etl", "data_cloud", "cloud"],
             secondary=["data_analytics", "software"],
             aliases=["data integration specialist", "data integration engineer"],
             kw=["Data Integration Specialist"],
             terms=["data", "integration", "etl", "sql", "pipelines", "apis"]),
        role("ma_specialist", "Marketing Automation Specialist", "crm_martech", "mid",
             ["marketing_automation", "crm", "email_marketing"],
             ["sfmc", "segmentation", "html_css"],
             aliases=["marketing automation specialist", "marketing automation"],
             kw=["Marketing Automation Specialist"],
             terms=["marketing_automation", "email", "crm", "campaign", "segmentation"]),
        role("campaign_ops", "Campaign Operations Specialist", "crm_martech", "mid",
             ["campaign", "email_marketing", "marketing_automation"],
             ["crm", "google_analytics", "segmentation"],
             aliases=["campaign operations", "campaign specialist", "campaign manager"],
             kw=["Campaign Operations Specialist"],
             terms=["campaign", "operations", "email", "automation", "reporting"]),
        role("crm_coordinator", "CRM Coordinator", "crm_martech", "entry",
             ["crm", "customer_service", "excel"],
             ["salesforce", "email_marketing", "reporting"],
             lang=True,
             aliases=["crm coordinator", "crm-koordinator"],
             kw=["CRM Coordinator"],
             terms=["crm", "coordinator", "customer", "campaign", "data"]),

        # --- CRM analyst / BI bridge ---------------------------------------
        role("crm_analyst", "CRM Analyst", "data_analytics", "mid",
             ["crm", "sql", "segmentation", "reporting"],
             ["power_bi", "salesforce", "excel"],
             secondary=["crm_martech"],
             aliases=["crm analyst", "crm-analytiker"],
             kw=["CRM Analyst"],
             terms=["crm", "analyst", "sql", "segmentation", "reporting", "data"]),
        role("bi_reporting", "BI / Reporting Specialist", "data_analytics", "mid",
             ["power_bi", "sql", "dashboards", "reporting"],
             ["excel", "data_visualization"],
             aliases=["bi specialist", "reporting specialist", "bi assistant", "business intelligence"],
             kw=["BI / Reporting Specialist", "BI Assistant"],
             terms=["bi", "power_bi", "dashboards", "reporting", "sql", "data"]),
        role("data_analyst", "Data Analyst", "data_analytics", "mid",
             ["sql", "excel", "power_bi", "statistics"],
             ["python", "data_visualization", "dashboards"],
             aliases=["data analyst", "dataanalytiker"],
             kw=["Data Analyst", "Junior Data Analyst"],
             terms=["data_analyst", "analytics", "sql", "statistics", "dashboards", "python"]),
        role("operations_analyst", "Operations Analyst", "data_analytics", "mid",
             ["excel", "sql", "reporting", "kpi"],
             ["power_bi", "statistics", "python"],
             secondary=["admin_ops"],
             aliases=["operations analyst", "operativ analytiker"],
             kw=["Operations Analyst"],
             terms=["operations", "analyst", "sql", "kpi", "reporting", "process"]),
        role("data_engineer", "Data Engineer", "data_analytics", "mid",
             ["sql", "python", "etl", "cloud"],
             ["docker", "dashboards", "integration"],
             secondary=["software"],
             aliases=["data engineer", "dataingenjör"],
             kw=["Data Engineer"],
             terms=["data_engineer", "etl", "sql", "python", "pipelines", "cloud"]),

        # --- Admin / ops ----------------------------------------------------
        role("reporting_assistant", "Reporting Assistant", "admin_ops", "entry",
             ["excel", "reporting", "office_tools"],
             ["sql", "power_bi", "kpi"],
             lang=True,
             aliases=["reporting assistant", "rapporteringsassistent"],
             kw=["Reporting Assistant"],
             terms=["reporting", "excel", "admin", "data"]),
        role("operations_coordinator", "Operations Coordinator", "admin_ops", "mid",
             ["coordination", "excel", "planning", "stakeholder"],
             ["reporting", "project_management"],
             lang=True,
             aliases=["operations coordinator", "operativ koordinator"],
             kw=["Operations Coordinator"],
             terms=["operations", "coordination", "planning", "stakeholder", "process"]),
        role("admin_coordinator", "Admin Coordinator", "admin_ops", "entry",
             ["administration", "excel", "planning", "office_tools"],
             ["coordination", "reporting"],
             lang=True,
             aliases=["admin coordinator", "administrative coordinator", "administrator"],
             kw=["Admin Coordinator", "Administrator"],
             terms=["admin", "coordination", "office", "scheduling", "support"]),
        role("junior_controller", "Junior Controller", "admin_ops", "mid",
             ["excel", "accounting", "financial_analysis", "reporting"],
             ["sql", "power_bi"],
             lang=True,
             aliases=["junior controller", "business controller", "controller"],
             kw=["Junior Controller", "Business Controller"],
             terms=["controller", "finance", "budget", "reporting", "excel"]),
        role("sales_coordinator", "Sales Coordinator", "sales", "entry",
             ["sales", "crm", "excel", "coordination"],
             ["account_management"],
             lang=True,
             aliases=["sales coordinator", "innesäljare"],
             kw=["Sales Coordinator"],
             terms=["sales", "crm", "coordination", "pipeline"]),
        role("account_manager", "Account Manager", "sales", "mid",
             ["account_management", "sales", "crm"],
             ["negotiation", "communication"],
             lang=True,
             aliases=["account manager", "kundansvarig"],
             kw=["Account Manager"],
             terms=["account_management", "sales", "crm", "clients", "relationship"]),

        # --- Digital marketing (off-lane for technical CRM CVs) -------------
        role("seo_specialist", "SEO Specialist", "digital_marketing", "mid",
             ["seo", "content", "google_analytics"],
             ["social_media"],
             aliases=["seo specialist", "seo"],
             kw=["SEO Specialist"],
             terms=["seo", "search", "content", "keywords", "ranking"]),
        role("social_media_specialist", "Social Media Specialist", "digital_marketing", "entry",
             ["social_media", "content"],
             ["seo", "google_analytics"],
             aliases=["social media specialist", "social media manager"],
             kw=["Social Media Specialist"],
             terms=["social_media", "content", "instagram", "community", "posts"]),
        role("content_specialist", "Content Marketing Specialist", "digital_marketing", "mid",
             ["content", "seo"],
             ["social_media", "google_analytics"],
             aliases=["content marketing", "content specialist", "copywriter"],
             kw=["Content Marketing Specialist"],
             terms=["content", "copywriting", "editorial", "seo"]),
        role("digital_marketing_specialist", "Digital Marketing Specialist", "digital_marketing", "mid",
             ["seo", "google_analytics", "content", "social_media"],
             ["email_marketing", "campaign"],
             aliases=["digital marketing specialist", "digital marknadsförare"],
             kw=["Digital Marketing Specialist"],
             terms=["digital", "marketing", "seo", "ads", "social_media", "campaign"]),

        # --- Software / IT (senior ones are off-lane / avoid for most) ------
        role("it_support", "IT Support Technician", "software", "entry",
             ["troubleshooting", "networking", "ticketing"],
             ["linux", "communication"],
             aliases=["it support", "supporttekniker", "helpdesk", "service desk"],
             kw=["IT Support Technician", "Supporttekniker"],
             terms=["support", "troubleshooting", "helpdesk", "networking"]),
        role("qa_engineer", "QA / Test Engineer", "software", "mid",
             ["testing", "test_automation"],
             ["python", "cicd", "apis"],
             aliases=["qa engineer", "test engineer", "testare"],
             kw=["QA Engineer", "Testare"],
             terms=["testing", "qa", "automation", "selenium"]),
        role("junior_developer", "Junior Developer", "software", "entry",
             ["javascript", "html_css", "git"],
             ["python", "apis", "sql"],
             aliases=["junior developer", "junior utvecklare", "trainee developer"],
             kw=["Junior Developer"],
             terms=["developer", "javascript", "react", "git", "code"]),
        role("software_developer", "Software Developer", "software", "mid",
             ["javascript", "git", "apis", "sql"],
             ["python", "java", "cloud", "docker"],
             aliases=["software developer", "systemutvecklare", "developer", "programmer"],
             kw=["Software Developer", "Systemutvecklare"],
             terms=["developer", "software", "code", "javascript", "apis", "git"]),
        role("devops_engineer", "DevOps Engineer", "software", "mid",
             ["docker", "cicd", "cloud", "linux"],
             ["kubernetes", "git"],
             aliases=["devops", "devops engineer", "platform engineer"],
             kw=["DevOps Engineer"],
             terms=["devops", "docker", "cloud", "pipelines", "infrastructure"]),
        role("data_scientist", "Data Scientist", "software", "senior",
             ["python", "machine_learning", "statistics", "sql"],
             ["data_visualization", "cloud"],
             aliases=["data scientist", "ml engineer", "machine learning engineer"],
             kw=["Data Scientist"],
             terms=["data_scientist", "machine_learning", "models", "python", "statistics"]),
        role("senior_developer", "Senior Developer", "software", "senior",
             ["javascript", "git", "apis", "leadership"],
             ["cloud", "docker", "architecture"],
             aliases=["senior developer", "lead developer", "tech lead"],
             kw=["Senior Developer"],
             terms=["senior", "developer", "architecture", "lead", "code"]),
        role("cybersecurity_specialist", "Cybersecurity Specialist", "software", "senior",
             ["security", "networking", "incident_response"],
             ["linux", "cloud"],
             aliases=["cybersecurity", "security specialist", "soc analyst"],
             kw=["Cybersecurity Specialist"],
             terms=["security", "cyber", "incident", "network", "threats"]),

        # --- Entry lanes ----------------------------------------------------
        role("assistant_nurse", "Assistant Nurse", "healthcare", "entry",
             ["patient_care", "elderly_care", "documentation"],
             ["communication"],
             lang=True,
             aliases=["assistant nurse", "undersköterska", "vårdbiträde", "care assistant"],
             kw=["Undersköterska", "Assistant Nurse"],
             terms=["care", "patient", "elderly", "documentation", "hemtjänst"]),
        role("registered_nurse", "Registered Nurse", "healthcare", "mid",
             ["nursing", "patient_care", "documentation"],
             ["medication"],
             lang=True,
             aliases=["registered nurse", "sjuksköterska", "legitimerad sjuksköterska"],
             kw=["Sjuksköterska", "Registered Nurse"],
             terms=["nurse", "nursing", "patient", "care", "medication"]),
        role("warehouse_worker", "Warehouse Worker", "logistics", "entry",
             ["warehouse", "inventory"],
             ["forklift"],
             aliases=["warehouse worker", "lagerarbetare", "lager"],
             kw=["Lagerarbetare", "Warehouse Worker"],
             terms=["warehouse", "lager", "picking", "inventory"]),
        role("logistics_coordinator", "Logistics Coordinator", "logistics", "mid",
             ["supply_chain", "excel", "planning", "inventory"],
             ["coordination", "reporting"],
             lang=True,
             aliases=["logistics coordinator", "logistikkoordinator"],
             kw=["Logistics Coordinator"],
             terms=["logistics", "supply_chain", "planning", "warehouse"]),
        role("truck_driver", "Truck Driver", "logistics", "entry",
             ["driving_license", "supply_chain"],
             ["forklift"],
             aliases=["truck driver", "lastbilsförare", "chaufför"],
             kw=["Lastbilsförare", "Truck Driver"],
             terms=["driver", "truck", "transport", "delivery"]),
        role("teaching_assistant", "Teaching Assistant", "education", "entry",
             ["pedagogy", "childcare", "communication"],
             [],
             lang=True,
             aliases=["teaching assistant", "elevassistent", "barnskötare", "lärarassistent"],
             kw=["Elevassistent", "Teaching Assistant"],
             terms=["school", "pedagogy", "children", "classroom"]),
        role("barista", "Barista / Café", "hospitality", "entry",
             ["customer_service", "communication"],
             [],
             lang=True,
             aliases=["barista", "café", "servitör", "waiter"],
             kw=["Barista", "Servitör"],
             terms=["café", "coffee", "service", "customers"]),
    ]


# Skill vocabulary for extraction (canonical skill -> surface variants).
SKILLS = {
    "sfmc": ["sfmc"], "ampscript": ["ampscript"], "ssjs": ["ssjs"],
    "marketing_automation": ["marketing_automation"], "crm": ["crm", "salesforce"],
    "data_cloud": ["data_cloud"], "integration": ["integration"], "apis": ["apis", "api"],
    "rest": ["rest"], "soap": ["soap"], "architecture": ["architecture", "solution_architect"],
    "email_marketing": ["email marketing", "newsletter", "e-post"], "segmentation": ["segmentation", "segmentering"],
    "campaign": ["campaign", "kampanj"], "seo": ["seo"], "social_media": ["social_media"],
    "content": ["content", "copywriting"], "google_analytics": ["google analytics", "ga4"],
    "excel": ["excel", "pivot"], "power_bi": ["power_bi"], "sql": ["sql"],
    "python": ["python", "pandas"], "statistics": ["statistics", "statistik", "regression"],
    "machine_learning": ["machine_learning", "scikit"], "etl": ["etl", "airflow"],
    "dashboards": ["dashboard", "instrumentpanel"], "data_visualization": ["tableau", "looker", "visualisering"],
    "kpi": ["kpi", "nyckeltal"], "reporting": ["reporting", "rapportering", "report"],
    "financial_analysis": ["budget", "forecasting", "controlling"], "accounting": ["accounting", "bokföring", "redovisning"],
    "javascript": ["javascript", "typescript", "react", "node"], "java": ["java "],
    "html_css": ["html", "css"], "git": ["git", "github"], "cloud": ["cloud", "aws", "azure", "gcp", "moln"],
    "docker": ["docker", "container"], "kubernetes": ["kubernetes", "k8s"], "cicd": ["cicd", "jenkins"],
    "linux": ["linux", "bash"], "networking": ["networking", "nätverk"], "troubleshooting": ["troubleshooting", "felsökning"],
    "testing": ["testing", "qa"], "test_automation": ["test_automation", "selenium", "cypress"],
    "security": ["security", "säkerhet"], "incident_response": ["incident", "soc", "siem"],
    "customer_service": ["customer_service", "kundtjänst", "kundsupport"], "communication": ["communication", "kommunikation"],
    "ticketing": ["ticketing", "zendesk", "ärendehantering"], "account_management": ["account_management"],
    "sales": ["sales", "försäljning"], "negotiation": ["negotiation", "förhandling"], "pipeline": ["pipeline"],
    "patient_care": ["patient_care"], "elderly_care": ["elderly_care", "hemtjänst"], "nursing": ["nursing", "sjuksköterska"],
    "documentation": ["documentation", "dokumentation", "journal"], "medication": ["medication", "läkemedel"],
    "warehouse": ["warehouse", "lager"], "forklift": ["forklift", "truck", "truckkort"], "inventory": ["inventory", "wms"],
    "supply_chain": ["supply_chain", "logistics"], "driving_license": ["driving_license"],
    "project_management": ["project_management", "scrum", "agile"], "coordination": ["coordination", "samordning"],
    "planning": ["planning", "planering", "scheduling"], "leadership": ["leadership", "ledarskap", "team lead"],
    "stakeholder": ["stakeholder", "intressent"], "office_tools": ["powerpoint", "word", "officepaket"],
    "administration": ["administration", "administrativ", "admin"], "pedagogy": ["pedagogy", "pedagogik", "teaching"],
    "childcare": ["childcare", "förskola"],
}


# ---------------------------------------------------------------------------
# Layer 2: retrieval index (TF-IDF over the role docs)
# ---------------------------------------------------------------------------
def role_doc_tokens(r):
    parts = [r["title"]] + r.get("aliases", []) + r.get("terms", []) \
        + r["required_skills"] + r["nice_skills"] + [r["domain"]] + r.get("secondary_domains", [])
    return tokenize(" ".join(parts))


def build_index_vectors(catalog):
    docs = {r["role_id"]: role_doc_tokens(r) for r in catalog}
    n = len(catalog)
    df = {}
    for toks in docs.values():
        for t in sorted(set(toks)):
            df[t] = df.get(t, 0) + 1
    idf = {t: round(math.log((n + 1) / (d + 1)) + 1.0, 5)
           for t, d in sorted(df.items())}

    vectors = {}
    for rid, toks in docs.items():
        tf = tf_weights(toks)
        vec = {t: tf[t] * idf.get(t, 0.0) for t in sorted(tf)}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors[rid] = {t: round(vec[t] / norm, 5) for t in sorted(vec)}
    return idf, vectors


def embed_query(text, idf):
    tf = tf_weights(tokenize(text))
    vec = {t: tf[t] * idf.get(t, 0.0) for t in tf if t in idf}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def cosine(q, r):
    if len(q) > len(r):
        q, r = r, q
    return sum(w * r.get(t, 0.0) for t, w in q.items())


# ---------------------------------------------------------------------------
# Layer 1: CV understanding (structured identity)
# ---------------------------------------------------------------------------
def extract_cv(text):
    low = " " + canon(text) + " "
    skills = [c for c, variants in SKILLS.items() if any((" " + v + " ") in (" " + low + " ") or v in low for v in variants)]
    catalog = build_catalog()
    roles = [r["title"] for r in catalog if any(a in low for a in r["aliases"])]

    swedish = "none"
    if re.search(r"svenska|swedish", low):
        native = r"(modersmål|native|flytande|fluent)"
        good = r"(good|goda|arbetsnivå|working|professional|b2|c1)"
        basic = r"(basic|grundläggande|sfi|a1|a2|b1)"
        after = lambda words: re.search(r"(svenska|swedish)\s*[:/,-]?\s*[^.;,\n]{0,30}" + words, low)
        before = lambda words: re.search(words + r"\s*[^.;,\n]{0,15}(svenska|swedish)", low)
        if after(native) or before(native):
            swedish = "native"
        elif after(good) or before(good):
            swedish = "good"
        elif after(basic) or before(basic):
            swedish = "basic"
        else:
            swedish = "basic"
    languages = []
    if "english" in low or "engelska" in low:
        languages.append("English")
    if swedish != "none":
        languages.append("Swedish (%s)" % swedish)

    years = [int(m) for m in re.findall(r"(\d{1,2})\+?\s*(?:years|år)", low)]
    max_years = max(years) if years else 0
    if re.search(r"\b(senior|lead|head|principal|architect|chef)\b", low):
        seniority = "senior"
    elif re.search(r"\b(junior|intern|trainee|student|entry)\b", low):
        seniority = "entry"
    elif max_years >= 6:
        seniority = "senior"
    elif max_years >= 2:
        seniority = "mid"
    else:
        seniority = "entry"

    return {
        "text": str(text or ""), "skills": skills, "roles": roles,
        "languages": languages, "swedish": swedish, "seniority": seniority,
        "years": max_years, "weak_swedish": swedish in ("none", "basic"),
    }


# ---------------------------------------------------------------------------
# Layer 3: rerank (semantic + skill + seniority + domain + language)
# ---------------------------------------------------------------------------
SEN_ORDER = {"entry": 0, "mid": 1, "senior": 2}


def rank_roles(profile, catalog, idf, vectors):
    qvec = embed_query(profile["text"], idf)
    cv_skills = set(profile["skills"])
    scored = []
    for r in catalog:
        sem = cosine(qvec, vectors[r["role_id"]])
        req = r["required_skills"]
        coverage = (sum(1 for s in req if s in cv_skills) / len(req)) if req else 0.0
        gap = SEN_ORDER[r["seniority"]] - SEN_ORDER.get(profile["seniority"], 0)
        sen_pen = 0.12 * gap if gap > 0 else 0.0
        lang_pen = 0.12 if (r["language_sensitive"] and profile["weak_swedish"]) else 0.0
        fit = 0.55 * sem + 0.30 * coverage - sen_pen - lang_pen
        scored.append({
            "role_id": r["role_id"], "title": r["title"], "domain": r["domain"],
            "field_id": r["field_id"], "field_label": r["field_label"],
            "seniority": r["seniority"], "semantic": round(sem, 4),
            "coverage": round(coverage, 3), "gap": gap,
            "fit": round(max(0.0, fit), 4),
            "missing": [s for s in req if s not in cv_skills],
            "language_sensitive": r["language_sensitive"],
            "keywords": r["search_keywords"],
        })
    scored.sort(key=lambda s: s["fit"], reverse=True)
    return scored


def primary_domain(profile, scored):
    """Domain of the strongest retrieval cluster (top fitting roles)."""
    weights = {}
    for s in scored[:6]:
        weights[s["domain"]] = weights.get(s["domain"], 0.0) + s["fit"]
    best_domain, best_weight = None, 0.0
    for domain, weight in weights.items():
        if weight > best_weight:
            best_domain, best_weight = domain, weight
    return best_domain


def bucket(profile, scored):
    pdomain = primary_domain(profile, scored)
    adjacent_domains = (DOMAIN_ADJACENCY.get(pdomain, set()) | {pdomain}) if pdomain else set()
    # "Confusable" domains: treat your domain as adjacent, but you don't treat
    # as yours (e.g. digital marketing vs a technical martech CV).
    confusable = set()
    if pdomain:
        for d, adj_of_d in DOMAIN_ADJACENCY.items():
            if d != pdomain and pdomain in adj_of_d and d not in adjacent_domains:
                confusable.add(d)
    best, adj, avoid = [], [], []
    for s in scored:
        overreach = s["gap"] >= 2 or (s["seniority"] == "senior" and s["gap"] > 0)
        on_lane = s["domain"] == pdomain
        near_lane = s["domain"] in adjacent_domains
        strong = s["fit"] >= 0.30 and (s["semantic"] >= 0.12 or s["coverage"] >= 0.5)
        if overreach:
            if s["fit"] >= 0.12:                     # aspirational over-reach with real signal
                avoid.append(s)
        elif on_lane and strong:
            best.append(s)
        elif (on_lane or near_lane) and (s["fit"] >= 0.20 or s["semantic"] >= 0.15):
            adj.append(s)
        elif s["domain"] in confusable:              # looks adjacent but isn't your lane
            avoid.append(s)
        elif s["fit"] >= 0.22:                       # off-lane but a notable, mismatched pull
            avoid.append(s)
        # else: irrelevant / near-zero fit -> not shown
    return pdomain, best[:6], adj[:5], avoid[:5]


# ---------------------------------------------------------------------------
# Synthetic CVs (fictional — demo + evaluation, never real data)
# ---------------------------------------------------------------------------
SYNTHETIC_CVS = [
    {
        "name": "SFMC / Martech Integration (senior)",
        "expect_domain": "crm_martech",
        "must_not_top": {"seo_specialist", "social_media_specialist", "software_developer", "cybersecurity_specialist"},
        "text": """Sasha Lindqvist — Senior Salesforce Marketing Cloud / Martech Integration Specialist
8 years in marketing technology and CRM automation.
Built SFMC journeys with AMPscript and SSJS, integrated systems via REST and SOAP APIs.
Strong SQL, Python, AWS and Azure. Led marketing automation architecture and integrations.
Target roles: Solution Architect, Martech Consultant, Integration Specialist.
Languages: English fluent, Swedish basic.""",
    },
    {
        "name": "Marketing / CRM (mid)",
        "expect_domain": "crm_martech",
        "text": """Alex Persson — Marketing Automation Coordinator, 4 years.
Salesforce Marketing Cloud, HubSpot, CRM, email marketing. Built segmentation and campaign flows.
Reported KPIs in Excel. English fluent, Swedish basic.""",
    },
    {
        "name": "Junior developer (entry)",
        "expect_domain": "software",
        "text": """Robin Lind — Junior Developer. Recent graduate.
JavaScript, React, HTML, CSS, Git, some Python and SQL. Built web apps and REST APIs.
English fluent, Swedish basic.""",
    },
    {
        "name": "Admin / reporting (mid)",
        "expect_domain": "admin_ops",
        "text": """Robin Ek — Administrative Coordinator, 5 years.
Strong Excel, reporting, planning and scheduling. Some SQL and Power BI.
Swedish flytande, English good.""",
    },
    {
        "name": "Assistant nurse (entry)",
        "expect_domain": "healthcare",
        "text": """Kim Andersson — Undersköterska. 3 years elderly care (hemtjänst).
Patient care and documentation (journal). Swedish modersmål, English basic.""",
    },
    {
        "name": "Warehouse / logistics (entry)",
        "expect_domain": "logistics",
        "text": """Jamie Berg — Lagerarbetare. 2 years warehouse, forklift (truckkort), inventory.
Driving license. Swedish good, English basic.""",
    },
]


def evaluate(catalog, idf, vectors):
    rows = []
    dom_hits = collapse_ok = 0
    for cv in SYNTHETIC_CVS:
        profile = extract_cv(cv["text"])
        scored = rank_roles(profile, catalog, idf, vectors)
        pdomain, best, adj, avoid = bucket(profile, scored)
        dom_ok = pdomain == cv["expect_domain"]
        dom_hits += int(dom_ok)
        top_ids = {s["role_id"] for s in (best + adj)[:5]}
        no_collapse = not (cv.get("must_not_top", set()) & top_ids)
        collapse_ok += int(no_collapse)
        rows.append({
            "cv": cv["name"], "extracted_skills": len(profile["skills"]),
            "seniority": profile["seniority"], "primary_domain": pdomain,
            "expected_domain": cv["expect_domain"], "domain_hit": dom_ok,
            "no_collapse": no_collapse,
            "best": [s["title"] for s in best[:4]],
            "adjacent": [s["title"] for s in adj[:3]],
            "avoid": [s["title"] for s in avoid[:3]],
        })
    n = len(SYNTHETIC_CVS) or 1
    return {
        "n_synthetic_cvs": len(SYNTHETIC_CVS),
        "primary_domain_accuracy": round(dom_hits / n, 3),
        "no_collapse_rate": round(collapse_ok / n, 3),
        "retrieval": "tf-idf cosine over role ontology (multilingual, synonym-expanded)",
        "embedding_upgrade": "BGE-M3 / Qwen3-Embedding via Nebius job + /cv-fit endpoint (same cosine contract)",
        "per_cv": rows,
    }


def write_json(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description="Build CV-fit engine index + evaluate")
    parser.add_argument("--index-out", default=os.path.join(DATA_DIR, "cv_match_index.json"))
    parser.add_argument("--samples-out", default=os.path.join(DATA_DIR, "sample_cvs.json"))
    parser.add_argument("--metrics-out", default=os.path.join(DATA_DIR, "cv_match_metrics.json"))
    args = parser.parse_args()

    print("Building CV-to-Market Fit engine index...")
    catalog = build_catalog()
    idf, vectors = build_index_vectors(catalog)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Attach the retrieval vector to each role for the browser matcher.
    roles_out = []
    for r in catalog:
        roles_out.append({**r, "vector": vectors[r["role_id"]]})

    index = {
        "last_updated": now, "version": INDEX_VERSION,
        "retrieval": "tf-idf-cosine",
        "domain_label": DOMAIN_LABEL,
        "domain_adjacency": {k: sorted(v) for k, v in DOMAIN_ADJACENCY.items()},
        "synonyms": SYNONYMS,
        "stopwords": sorted(STOPWORDS),
        "idf": idf,
        "skill_vocab": [{"skill": k, "variants": v} for k, v in SKILLS.items()],
        "roles": roles_out,
    }
    write_json(args.index_out, index)

    samples = {
        "last_updated": now,
        "note": "Synthetic, fictional CVs for demoing the CV Job Fit Scanner. No real or personal data.",
        "cvs": [{"name": c["name"], "text": c["text"]} for c in SYNTHETIC_CVS],
    }
    write_json(args.samples_out, samples)

    metrics = evaluate(catalog, idf, vectors)
    write_json(args.metrics_out, {"last_updated": now, "version": INDEX_VERSION, "metrics": metrics})

    print(f"  roles indexed         : {len(catalog)}")
    print(f"  idf vocabulary        : {len(idf)}")
    print(f"  synthetic CVs         : {metrics['n_synthetic_cvs']}")
    print(f"  primary-domain accuracy: {metrics['primary_domain_accuracy']}")
    print(f"  no-collapse rate      : {metrics['no_collapse_rate']}")
    for row in metrics["per_cv"]:
        print(f"    - {row['cv'][:34]:34} -> {row['primary_domain']:14} best={row['best'][:3]}")
    print(f"Wrote {args.index_out}")
    print(f"Wrote {args.samples_out}")
    print(f"Wrote {args.metrics_out}")


if __name__ == "__main__":
    main()
