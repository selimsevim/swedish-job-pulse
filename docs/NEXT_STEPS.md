# Next steps (handoff)

_Status: `railway-cv-fit-proxy` is merged into `main` and pushed (merge `b792f59`).
The merge kept the branch's coherent, eval-passing data over the automated W24
weekly refresh; the next weekly bot run restores raw freshness on top of the new
pipeline. Eval verified green on the merge result (`--strict` exit 0)._

## Done this session (committed)
Section 3 "analysis intelligence" + supporting work:
- **Occupation-group skill gaps** (`c074c3b`) — gaps now come from the candidate's
  occupation group's real ad demand, not the broad dev-dominated field. A data
  analyst no longer gets C++/Java. Data: `scripts/process_field_skills.py` now
  aggregates per occupation group over 2 years; `data/field_skills.json` rebuilt.
- **Per-role group anchoring + eval harness** (`8bca9d8`) — `ROLE_OCC_GROUP` maps
  each multi-lane Data/IT role to its real SSYK group (analyst / dev / support /
  test / ops). `scripts/evaluate_cv_fit.py` runs the full `analyze_cv` over 26
  labelled CVs and scores domain routing, occupation-group routing and gap
  relevance; `--strict` gates CI (`.github/workflows/ci.yml`).
- **Runtime data loading** (`2398a25`) — `CV_FIT_DATA_URL` makes the endpoint pull
  the latest data at startup (no image rebuild); `/health` reports data freshness.
- **Ontology growth** (`8a21bcd`) — education + hospitality grown from the taxonomy
  (preschool/primary teacher, childminder, chef, waiter); 58 roles. Neural index
  (BGE-M3) regenerated.
- Also lands the prior session's **LLM CV extraction** (inert without a model).

Current eval: domain 1.0, top-3 1.0, no-collapse 1.0, group routing 1.0 (9/9),
gap relevance 1.0 (5/5). Run: `python scripts/evaluate_cv_fit.py --strict`.

## Test next session (endpoints are torn down)
1. Recreate the Nebius endpoints (TF-IDF + grounded-LLM). See `nebius/README.md`
   and memory note `nebius-ghcr-deploy`.
2. Verify the GPU path: a data-analyst CV returns analyst-lane gaps (Dynamics/CRM/
   SQL), not C++/Java, and `matched_occupation_group` is populated.
3. Optional: set `CV_FIT_DATA_URL` (object storage or raw repo `…/data`) and
   confirm `/health` `data.refreshed_from_url` lists the 4 files.

## Submission (your part)
- ~~**Push the repo public** (merge `railway-cv-fit-proxy` → `main`, push).~~ ✅ done
  (merge `b792f59`). Repo was already public; main now carries all CV-fit work.
- **Set the live URL** — deploy on Railway, point `NEBIUS_CV_FIT_URL` +
  `NEBIUS_CV_FIT_TOKEN` at the running GPU endpoint, confirm a report renders,
  then submit that URL. The endpoint must stay up through judging (the proxy only
  accepts an `llm:` backend). Deadline June 30.
- **Blog post** (≥600 words, `#NebiusServerlessChallenge`) — full write-up in
  `docs/blog-post.md`; project doc in `docs/DOCUMENTATION.md`. Angle: grounded-LLM
  endpoint + occupation-group gaps + the eval harness that caught the
  nurse→pharmacist drift.
- **Video walkthrough**, reproducibility pass (`run_local_nebius.sh`).

## Investigated and intentionally NOT done
- **Region outlook at occupation-group granularity** — investigated and dropped.
  The JobTech search API caps `stats.limit` at 30, so per-region occupation-group
  counts are too sparse: the groups that would differ from their field (analyst
  4/21 regions, IT support/test 0/21) are unrankable, while the well-covered ones
  (teacher 21/21, chef 19/21, dev 14/21) track their parent field geographically
  anyway. Shipping it would add a noisy/misleading signal — kept the robust
  field-level region outlook instead. (Reverted the pipeline change.)

## Open quality/ops ideas (not requested this session)
- Rate-limit + size-cap `/api/cv-fit` on the Railway proxy (public GPU app).
- Result caching (hash of CV + region) to cut repeat GPU calls.
- Scale-to-zero / on-demand Nebius serverless so idle time doesn't bill.
- More ontology growth (sales, manufacturing, maintenance, beauty still have
  1–2 roles each) — same recipe: add roles + `ROLE_OCC_GROUP` anchors validated
  against `data/field_skills.json` groups, rebuild index, regen neural index
  (`scripts/build_neural_role_index.py`, BGE-M3 cached locally), `evaluate_cv_fit.py --strict`.
