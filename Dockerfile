FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt requirements-ml.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip install --no-cache-dir -r requirements-ml.txt

COPY . .

RUN ./scripts/rebuild_career_reality.sh

EXPOSE 8000

CMD ["python3", "-m", "http.server", "8000", "--bind", "0.0.0.0"]
