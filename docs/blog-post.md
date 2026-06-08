# Reading a CV against the real Swedish job market, without making things up

*Building Swedish Job Pulse: a public-data CV-to-market fit engine, with a
grounded LLM on Nebius Serverless AI.*

`#NebiusServerlessChallenge`

---

Most job searches start with a guess. You find a posting, decide it "looks about
right", and spend the next few weeks applying — often to roles that are too
crowded, too senior, in the wrong region, or that quietly expect fluent Swedish.
Job boards are excellent at telling you *what jobs exist*. They are not built to
answer the question that actually shapes your next month: **given my CV, which
roles do I credibly fit right now, and if one is a stretch, what should I fix
first?**

You can, of course, paste your CV into a general-purpose chatbot and ask. It will
answer instantly and confidently — and it will invent things. Roles that aren't
really in demand, skill gaps pulled from nowhere, numbers with nothing behind
them. For a decision that costs weeks of your life, a confident hallucination is
worse than no answer.

So I built **Swedish Job Pulse**: a small website that reads your CV, places it on
a map of real Swedish roles, and grounds every piece of advice in **public
job-ad data** rather than opinion. It runs on **Nebius Serverless AI**, and the
interesting part is not that it uses an LLM — it is *how little* the LLM is
allowed to decide.

## The product, in one screen

You upload a PDF CV (or paste the text) and optionally choose a region. The PDF is
parsed **in your browser** — the file itself never leaves your machine — and the
extracted text is sent for a single analysis and never stored. Back comes a
one-page report: best-fit roles now, stretch roles, roles to skip for now, the
skills your CV is missing, specific ways to strengthen it, search keywords, a
7-day plan, and a compact market signal. The interface is in English and Swedish.

## Grounded, not invented

The core design rule is a hard split between **facts** and **language**.

Deterministic code owns the facts. The CV is matched against a role ontology with
a reproducible multilingual TF-IDF vector space and synonym expansion — so
`SFMC`, `Salesforce Marketing Cloud`, and `Martech` collapse to the same thing,
and a specialist martech CV is not flattened into generic "digital marketing".
The matched roles, the missing skills, the market signal, and the cross-region
demand ranking all come out of this layer, from real data.

Only then does the language model — **Qwen2.5-7B-Instruct**, self-hosted on a
single NVIDIA L40S — get involved, and only to *write*. It produces one decisive
headline, a short "why", a region strategy, and CV-specific improvement advice,
with greedy decoding for reproducibility and constrained to the role titles it
was handed. It cannot name a role or a number the facts didn't provide. Before
anything is shown, the output is validated: the model must name a real best-fit
role, must not soften the market signal ("high crowding" cannot quietly become
"moderate"), and must not lead with the region. If it fails, the request is
rejected rather than served. There is no silent fall-back to a weaker answer.

## The detail that makes it honest: occupation-group gaps

Here is the bug that taught me the most. A data analyst's CV sits inside the
broad, developer-dominated "Data/IT" field. If you compute skill gaps against the
*whole field*, the tool cheerfully tells the analyst to go learn C++ and Java.
That is the kind of plausible-sounding nonsense that makes people distrust these
systems.

The fix was to anchor every role to its real **JobTech occupation group** —
analyst/architect, software developer, IT support, test, ops — and to draw the
gaps from *that group's* actual ad demand, aggregated from two years of enriched
public ads. Now a data analyst sees analyst-lane gaps (SQL depth, BI tools,
Dynamics/CRM), and a developer sees developer gaps. Same field, different lanes,
different advice.

## An evaluation harness that catches drift

Quality is gated, not hoped for. A small harness runs the full analysis pipeline
over labelled synthetic CVs and scores domain routing, "no-collapse" (specialists
aren't flattened into generic jobs), occupation-group routing, and gap relevance
(no C++/Java for a non-developer). It runs in CI with a `--strict` flag that fails
the build on any regression.

This is not theatre. While iterating, the harness is exactly what caught a nurse's
CV drifting toward pharmacist-style advice, and analysts inheriting developer
gaps, before any of it reached a user. It currently passes cleanly across the
board, and the gate means that kind of drift can't sneak back in unnoticed.

## Why Nebius Serverless AI fits

Two shapes of work, two serverless uses:

- **Jobs (CPU)** for the pipeline — collecting public ads, training the
  demand-trend model, scoring, and building the role index. It starts, writes its
  JSON artifacts, validates them, and exits. One container runs the whole rebuild.
- **An Endpoint (GPU)** for the `/cv-fit` advisor — the grounded LLM on an L40S.
  This is where the GPU genuinely earns its place: retrieval is cheap and
  deterministic, but turning evidence into specific, region-aware advice is real
  model work. The endpoint is token-protected and the public app reaches it
  through a server-side proxy on Railway, so the token never touches the browser.

Nothing here needs an always-on fleet. The Jobs run and exit; the endpoint comes
up for inference and is torn down when idle, so it doesn't bill while unused.

## Being honest about the model

A note I kept in the product and the docs: the demand-trend model is **not** a
precise vacancy-count predictor. On the count target, simple persistence actually
has the lower error (MAE 80.90 vs the model's 90.73). Where the model wins is
**trend direction** — accuracy 0.607 vs 0.227, macro-F1 0.477 vs 0.123 — so the
product only ever uses it as a *directional* advisory signal, never as a hard
forecast. Public job ads are a demand signal, not the whole labour market and not
a guarantee of employment. The tool says all of this plainly.

## Closing

Swedish Job Pulse is a small example of using serverless ML for public-interest
decision support: not replacing human judgement, but making labour-market risk
visible *before* someone spends weeks applying in the wrong direction. The
engineering lesson that stuck with me is that the value wasn't in adding a bigger
model — it was in deciding, precisely, what the model is *not* allowed to do.

*Built on public Arbetsförmedlingen / JobTech data. No personal data, no private
datasets, no committed secrets.*
