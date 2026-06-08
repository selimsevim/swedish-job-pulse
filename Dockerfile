FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt requirements-ml.txt requirements-railway.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir -r requirements-ml.txt \
    && python -m pip install --no-cache-dir -r requirements-railway.txt

COPY . .

RUN ./scripts/rebuild_career_reality.sh

EXPOSE 8000

# Default command serves the static site (local `docker run`, static hosting).
# requirements-railway.txt also installs fastapi/uvicorn/httpx, so Railway can
# override this with the proxy start command (see railway.json):
#   python -m uvicorn app.server:app --host 0.0.0.0 --port $PORT
CMD ["python3", "-m", "http.server", "8000", "--bind", "0.0.0.0"]
