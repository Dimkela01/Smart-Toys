# llama.cpp server (ARCHITECTURE.md §6.3). The upstream image is multi-arch and already
# holds llama-server; this layer only adds the registry-driven launcher, so that no model
# file name is ever written into a Dockerfile or a compose command (docs/CLAUDE.md §3).
#
# Pinned by digest, resolved 2026-11-25 from ghcr.io/ggml-org/llama.cpp:server
# (linux/amd64, linux/arm64, linux/s390x).
FROM ghcr.io/ggml-org/llama.cpp:server@sha256:b0cd5490eefff30b40dcd47f7249a7d7211136908f73fe440a2a86b35a22b23b

# python3 is already present; python3-yaml comes from apt rather than pip so the image
# keeps its own package manager's view of the world
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-yaml curl \
 && rm -rf /var/lib/apt/lists/*

COPY common /srv/inference/common
COPY llm/launch.py /srv/inference/launch.py

ENTRYPOINT ["python3", "/srv/inference/launch.py"]
