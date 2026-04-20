FROM python:3.11-slim

WORKDIR /app

# System deps:
#  - libgomp1  -> LightGBM OpenMP runtime
#  - curl      -> health probe
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 \
      curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first so the image layer is cacheable
COPY service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the parts the service actually needs at runtime
COPY service ./service
COPY models ./models
COPY data/gtfs_static ./data/gtfs_static
COPY data/static_summary.json ./data/static_summary.json

ENV PYTHONUNBUFFERED=1 \
    MODELS_DIR=/app/models \
    STATIC_DIR=/app/data/gtfs_static \
    PORT=8000

EXPOSE 8000

# Railway/Render/Fly all inject $PORT; honour it. Fall back to 8000 locally.
# 2 workers: each loads LightGBM + static GTFS (~80 MB RSS), fits 512 MB plan.
# Each worker has its own in-process /plan TTL cache and httpx keepalive pool -
# the cache won't share across workers, so cache-hit ratio halves, but total
# p99 under concurrent load drops substantially vs a single worker.
CMD ["sh", "-c", "uvicorn service.app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
