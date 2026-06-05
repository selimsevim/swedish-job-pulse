#!/usr/bin/env python3
"""Precompute neural role embeddings (e.g. BGE-M3) for the /cv-fit endpoint.

Reads the role ontology from data/cv_match_index.json, embeds each role's text
with a multilingual embedding model, and writes a small index the neural
endpoint loads at boot (so it does not re-embed 41 roles every cold start).

Output (default): nebius/cv_fit_endpoint/neural_role_index.json
  { "model": "BAAI/bge-m3", "dim": 1024, "generated": "...", "count": 41,
    "roles": [ { "role_id": "...", "vector": [ ... ] }, ... ] }

The role-text construction is kept identical to cv_fit_core._Engine._role_text
so query/role embeddings live in the same space.

Run (needs torch + sentence-transformers; runs natively on CPU/GPU/MPS):
    python3 scripts/build_neural_role_index.py --model BAAI/bge-m3
"""

import argparse
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
DEFAULT_OUT = os.path.join(ROOT, "nebius", "cv_fit_endpoint", "neural_role_index.json")


def role_text(role):
    # MUST match cv_fit_core._Engine._role_text.
    parts = [role["title"]] + role.get("aliases", []) + role.get("terms", []) \
        + role.get("required_skills", []) + role.get("nice_skills", [])
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Precompute neural role embeddings")
    ap.add_argument("--model", default=os.environ.get("CV_FIT_EMBEDDING_MODEL", "BAAI/bge-m3"))
    ap.add_argument("--index", default=os.path.join(DATA_DIR, "cv_match_index.json"))
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--round", type=int, default=6, help="decimal places to store")
    args = ap.parse_args()

    with open(args.index, "r", encoding="utf-8") as fh:
        roles = json.load(fh)["roles"]

    from sentence_transformers import SentenceTransformer
    print(f"Loading {args.model} ...")
    model = SentenceTransformer(args.model)
    texts = [role_text(r) for r in roles]
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    dim = int(len(embs[0]))

    out = {
        "model": args.model,
        "dim": dim,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(roles),
        "normalized": True,
        "roles": [
            {"role_id": r["role_id"],
             "vector": [round(float(x), args.round) for x in embs[i]]}
            for i, r in enumerate(roles)
        ],
    }
    tmp = args.out + ".tmp"
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    os.replace(tmp, args.out)
    print(f"Wrote {args.out}  (model={args.model}, dim={dim}, roles={len(roles)})")


if __name__ == "__main__":
    main()
