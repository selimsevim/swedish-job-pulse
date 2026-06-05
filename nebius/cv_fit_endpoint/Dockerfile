# Optional /cv-fit endpoint image. Builds the data artifacts, then serves the
# FastAPI app. Runs in the reproducible TF-IDF fallback out of the box; set
# CV_FIT_EMBEDDING_MODEL (and uncomment the neural deps in
# requirements-endpoint.txt) to use BGE-M3 / Qwen3 neural embeddings.
#
# Built from the repository root:
#   docker build -f nebius/cv_fit_endpoint/Dockerfile -t cv_fit_endpoint .
#   docker run --rm -p 8080:8080 cv_fit_endpoint
#
# No secrets, no credentials, no CV storage.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r nebius/cv_fit_endpoint/requirements-endpoint.txt \
    && python -m pip install --no-cache-dir -r requirements-ml.txt || true

# Ensure the CV index exists (does not require the optional ML deps).
RUN python3 scripts/build_cv_match_index.py

ENV CV_FIT_INDEX_PATH=/app/data/cv_match_index.json \
    CV_FIT_CAREER_PATH=/app/data/career_reality.json

EXPOSE 8080
WORKDIR /app/nebius/cv_fit_endpoint
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
