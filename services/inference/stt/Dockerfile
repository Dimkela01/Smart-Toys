# faster-whisper on CPU with int8 (ARCHITECTURE.md §6.2). No GPU, no model name: the
# weights are resolved through models/registry.yaml at startup (docs/CLAUDE.md §3).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY stt/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /srv/inference/common
COPY stt/app.py /srv/inference/app.py

WORKDIR /srv/inference
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
