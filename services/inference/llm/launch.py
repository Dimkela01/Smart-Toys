#!/usr/bin/env python3
"""Start llama-server for the model the registry marks active (ARCHITECTURE.md §6.3).

Flags follow §6.3 for the server profile: two slots of `context` tokens each, no GPU
offload, one thread per physical core, and --jinja so the model's own chat template is
used. Nothing here names a model: the id, the file and the context size all come from
models/registry.yaml, so changing model is a registry edit and a restart.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "/srv/inference")

from common import registry


def main() -> None:
    model = registry.default_llm()
    model_id = str(model["id"])
    path = registry.weight_file("models", model_id, str(model["file"]))

    # §6.3: --parallel slots, each with the registry's context budget
    slots = int(os.environ.get("LLM_PARALLEL", "2"))
    context = int(model["context"]) * slots
    threads = os.environ.get("LLM_THREADS") or str(os.cpu_count() or 4)

    # pairs, so one flag and its value stay on one line however the formatter folds this
    flags = [
        ("--model", str(path)),
        # the API addresses the model by its registry id
        ("--alias", model_id),
        ("--ctx-size", str(context)),
        ("--parallel", str(slots)),
        # CPU only: Docker on macOS has no Metal, and the reference board has no CUDA
        ("--n-gpu-layers", "0"),
        ("--threads", threads),
        ("--host", "0.0.0.0"),
        ("--port", os.environ.get("LLM_PORT", "8080")),
    ]
    argv = ["/app/llama-server", *[word for pair in flags for word in pair], "--jinja"]

    print(f"llm: {model_id} ({model['quant']}, {model['size_mb']} MB)", flush=True)
    print(f"llm: {context} tokens over {slots} slots, {threads} threads", flush=True)
    print(f"llm: {Path(path).name}", flush=True)
    os.execv(argv[0], argv)


if __name__ == "__main__":
    main()
