FROM python:3.11-slim

WORKDIR /app

# System deps for LightGBM
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY service ./service
COPY models ./models
COPY data/static_summary.json ./data/static_summary.json

ENV PYTHONUNBUFFERED=1 \
    MODELS_DIR=/app/models \
    STATIC_DIR=/app/data

EXPOSE 8000

CMD ["uvicorn", "service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
