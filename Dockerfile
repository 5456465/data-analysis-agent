FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY deployment/olist_duckdb_artifact.json ./deployment/olist_duckdb_artifact.json
COPY scripts/stage_database.py ./scripts/stage_database.py

RUN python scripts/stage_database.py

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir .

COPY app.py ./app.py

EXPOSE 8501 8000

CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
