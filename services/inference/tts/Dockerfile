# Text-to-speech: Kokoro-82M for English, a Piper-class VITS voice for Serbian
# (ARCHITECTURE.md §6.4). No voice name is baked in; both come from the registry.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    # everything runs locally: fail loudly rather than quietly fetching a model at
    # runtime (docs/CLAUDE.md §2). Weights come from models/weights via `make models`.
    HF_HUB_OFFLINE=1

# espeak-ng: Kokoro's phonemizer falls back to it for out-of-dictionary words, and the
# Piper voice uses it for Serbian
RUN apt-get update \
 && apt-get install -y --no-install-recommends espeak-ng curl \
 && rm -rf /var/lib/apt/lists/*

# CPU-only torch; the default index would pull the CUDA build
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY tts/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Kokoro's English phonemizer needs this spaCy model. Installed at build time, because
# the library otherwise downloads it on first use - which HF_HUB_OFFLINE would not stop
# and a service with no network would fail on.
RUN pip install --no-cache-dir \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

COPY common /srv/inference/common
COPY tts/app.py /srv/inference/app.py

WORKDIR /srv/inference
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "info"]
