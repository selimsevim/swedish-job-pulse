# Swedish Job Pulse — Documentation

This document starts with the plain-language idea and gets more technical as it
goes down. If you only want the "what and why", the first four sections are
enough. The later sections are for anyone who wants to see how it actually works.

---

## Problem

Looking for a job in Sweden, most people guess. You find a posting, decide it
"looks about right", and spend weeks applying, often to roles that are too
crowded, too senior, in the wrong region, or that quietly expect fluent Swedish.
Job boards are good at answering *"what jobs exist?"*. They are not built to
answer the question that actually decides your next month:

> **Given my CV, which roles do I credibly fit right now in the Swedish market,
> and if a role is a stretch, what should I fix first?**

Generic AI career chatbots will happily answer that, but they make things up:
invented roles, invented demand, confident numbers with nothing behind them.
That is worse than no answer, because it feels authoritative.

## Proposal

Build a small, honest tool that does one thing well: read a CV, place it on a
map of real Swedish roles, and ground every piece of advice in **public
job-ad data** rather than opinion.

Three principles guide it:

1. **Public data only.** No personal data, no private datasets, no scraping.
   Everything is built on Arbetsförmedlingen / JobTech open data.
2. **Grounded, not invented.** A language model may *explain* the result, but it
   may never *decide* it. The facts (which roles match, which skills are missing,
   how the market looks) come from deterministic code over real data. The model
   only turns those facts into readable advice, and is constrained to them.
3. **Honest about its limits.** Public job ads are a demand signal, not the whole
   labour market and not a guarantee of employment. The tool says so.

## Solution

**Swedish Job Pulse** is a website with one entry point: a **CV Job Fit Scanner**.

You upload a PDF CV (or paste the text) and, optionally, pick a region. The PDF
is read **in your browser** — the raw file never leaves your machine. The
extracted text is sent once for analysis and is not stored. In return you get a
one-page report:

- **Best-fit roles now**, **stretch roles**, and **roles to skip for now**
- **What your CV is missing** — the skills real ads in your lane ask for
- **How to strengthen your CV** — specific fixes for *your* CV, not boilerplate
- **Search keywords** and a **7-day action plan**
- A compact **market signal** (demand direction, crowding, regional fit, remote)

The interface is available in **English and Swedish**. (The AI analysis itself is
written in English; a note says so when the UI is in Swedish.)

## Nebius's Role

The intelligence runs on **Nebius Serverless AI**, used in two complementary ways:

- **Serverless AI Jobs (CPU).** The data pipeline — collecting public ads,
  training the demand-trend model, scoring, and building the role index — is
  finite, batch work that starts, writes JSON artifacts, and exits. That is
  exactly what a serverless Job is for. One container runs
  `./scripts/rebuild_career_reality.sh` end to end.
- **Serverless AI Endpoint (GPU).** The `/cv-fit` endpoint is a **grounded-LLM
  advisor** running **Qwen2.5-7B-Instruct on a single NVIDIA L40S**. This is
  where the GPU earns its place: deterministic retrieval produces the facts, and
  the model writes the verdict, the reasoning, and the region strategy —
  constrained to those facts. It is a model-serving + RAG endpoint, token-
  protected, that the public app calls through a secure proxy.

Serverless fits because nothing here needs an always-on fleet: the Jobs run and
exit, and the endpoint can be brought up for live inference and torn down when
idle so it does not bill while unused.

---

## How a CV becomes a report

The pipeline has four layers. The first three produce **facts**; only the last
turns them into prose.

1. **Extraction.** The PDF is parsed in-browser into `{skills, roles, languages,
   seniority}`. On the endpoint, the LLM can also read the CV to recover skills
   expressed in Swedish, via tools, or by paraphrase — but it may only pick
   tokens from a fixed skill vocabulary, so it cannot invent a skill.
2. **Retrieval + ranking.** The profile is vectorised and matched against a role
   ontology (`data/cv_match_index.json`) using a reproducible **multilingual
   TF-IDF vector space** with synonym/domain expansion (so `SFMC = Salesforce
   Marketing Cloud = Martech`, and a technical martech CV is not flattened into
   "digital marketing"). Results are reranked by skill overlap, seniority,
   domain fit, and Swedish-language fit, then enriched with public demand,
   crowding, regional, and trend signals. The reranker is **domain-agnostic**:
   there are no role names hard-coded in the logic.
3. **Gap analysis.** Which skills block stronger matches, drawn from real ad
   demand (see the next section).
4. **Explanation.** The grounded LLM writes the verdict, the "why", the region
   strategy, and the CV-specific improvements — using only the facts above.

## Occupation-group skill gaps

This is the detail that makes the advice trustworthy. A data analyst's CV sits
inside the broad, developer-dominated "Data/IT" field. If you compute skill gaps
against the *whole field*, you tell the analyst to go learn C++ and Java — which
is nonsense for that role.

Instead, the endpoint anchors each role to its real **JobTech occupation group**
(analyst/architect, software developer, IT support, test, ops, and so on) and
draws the gaps from *that group's* actual ad demand
(`data/field_skills.json`, aggregated per occupation group from two years of
enriched ads). A data analyst therefore sees analyst-lane gaps (SQL depth, BI
tools, Dynamics/CRM), not developer gaps. It falls back to whole-field demand
only where no group lane applies.

## The grounded-LLM endpoint

The division of labour is strict and deliberate:

- **Deterministic code owns the facts.** Matched role titles, missing skills,
  the market signal, and the cross-region demand ranking are all produced by
  reproducible code over public data.
- **The LLM owns the language.** Qwen2.5-7B writes one decisive headline, a
  short "why", and a region strategy, with **greedy decoding** (so the same input
  gives the same output) and **constrained to the role titles it is given**. It
  cannot name a role or a number that the facts did not provide.

The output is validated before it is shown: the model must name a real best-fit
role, must not soften the market signal (high crowding cannot quietly become
"moderate"), and must not lead with the region. If validation fails, the request
is rejected rather than served — there is no silent fall-back to a weaker answer.

## CV-specific improvements

The "how to strengthen your CV" advice used to be a fixed template
("add measurable impact…"). Now the detection of *which* weakness applies is
still reasoned from your CV (no quantified impact, thin skills section, language
level unstated, senior scope unclear), and the LLM phrases each one **specific to
your CV** — for example, "you list SQL and Power BI but no outcomes: quantify your
reporting impact, which analyst ads ask for." Nothing in the report is blind
boilerplate; the deterministic template only survives as a fall-back when the LLM
is off.

## The market-intelligence (ML) layer

Behind the report sits a small forecast model
(`scripts/train_career_signal_model.py`): a `HistGradientBoostingRegressor` that
predicts active-ad demand about four weeks ahead per occupation group, converted
into a direction class (`grow` / `stable` / `decline`). Features are lagged ad
counts (previous week, 4- and 8-week averages, 4-week relative trend) plus remote
share, entry-level share, a search-attention gap, and the occupation-field code.
It uses a temporal holdout (newest weeks held out) and a fixed random state.

Current metrics, reported honestly:

| Metric | ML model | Baseline persistence |
|---|---:|---:|
| MAE | `90.73` | `80.90` |
| Trend accuracy | `0.607` | `0.227` |
| Trend macro-F1 | `0.477` | `0.123` |

The model is **not** an exact vacancy-count predictor — baseline persistence has
the lower MAE on the count target. Its value is **trend direction**, where it
clearly beats the baseline, and the product uses direction as an advisory signal
only. If scikit-learn is unavailable, a pure-stdlib persistence fallback still
writes valid artifacts.

## Data sources

Public Arbetsförmedlingen / JobTech data only, no API key required:

- Active ad counts, positions, remote share, and entry-level share by occupation
- Regional occupation-field specialisation
- Search attention vs demand, as a crowding-risk proxy
- The JobTech taxonomy: occupation groups, fields, regions, and skills

## Deployment: Railway + Nebius

The public site is hosted on **Railway**, not GitHub Pages, because it needs one
small server-side job: keeping the Nebius token secret.

```
Browser  ->  Railway app (app/server.py)  ->  Nebius /cv-fit endpoint
            |-- serves index.html / app.js / style.css / data/*.json
            |-- POST /api/cv-fit  --(Authorization: Bearer <token>)-->  endpoint
```

The browser calls the same-origin route `POST /api/cv-fit`; the server attaches
the bearer token and forwards to the endpoint, so the token is never in anything
the browser receives. The proxy also checks endpoint health and only accepts an
`llm:` backend — if the grounded LLM is not serving, the site shows an error
rather than a degraded answer. Server-side variables: `NEBIUS_CV_FIT_URL`,
`NEBIUS_CV_FIT_TOKEN`, and optional `NEBIUS_CV_FIT_TIMEOUT`.

## Evaluation and CI

Quality is gated, not assumed. `scripts/evaluate_cv_fit.py` runs the full
`analyze_cv` pipeline over labelled synthetic CVs and scores:

- **domain routing** — does the CV land in the right family?
- **no-collapse** — specialist profiles are not flattened into generic jobs
- **occupation-group routing** — a data analyst lands in the analyst lane, not
  the developer one
- **gap relevance** — no C++/Java surfaced to a non-developer

It currently passes cleanly (domain 1.0, group routing 1.0, gap relevance 1.0,
no-collapse 1.0). `--strict` fails the build on any routing or gap regression and
runs in CI, so the kind of drift this is designed to catch — a nurse drifting
toward pharmacist-style advice, or an analyst inheriting developer gaps — cannot
slip in unnoticed.

## Privacy

PDFs are parsed in the browser; the extracted text is sent for a single request
and is **never stored or logged** (the access log records the path `/api/cv-fit`,
not the body). No personal data, no private data, and no secrets are committed.
The Nebius token lives only in Railway's server-side variables.

## Known limitations

- Built on public job-ad signals, not all jobs in Sweden, and not a guarantee of
  employment.
- Employers are not required to publish every job through JobTech.
- The forecast is national by occupation group; regional fit is a transparent
  specialisation weight, not a regional time-series forecast.
- The model improves trend classification, not count MAE.
- Search pressure is not the same as applicant count.
- CV analysis is advisory and should not be treated as hiring certainty.

## Reproduce it

```bash
git clone https://github.com/selimsevim/swedish-job-pulse.git
cd swedish-job-pulse
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-ml.txt
./scripts/rebuild_career_reality.sh   # builds + validates all data artifacts
python3 -m http.server 8000
```

Open <http://127.0.0.1:8000/index.html>. Docker and the Railway + Nebius
deployment are described in the [README](../README.md) and
[`nebius/README.md`](../nebius/README.md).
