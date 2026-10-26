# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12-slim

FROM python:${PYTHON_VERSION} AS builder

# speed up the installed process and reduce the weight of the packages
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON_PREFERENCE=only-system

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
# pinned so the resolver behaves identically on every build, not whatever
# uv happens to release the day this image is built
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# the runtime stage copies .venv across, and its symlinks only resolve if the
# interpreter is this image's own python rather than a uv-downloaded one
RUN uv sync --locked --no-dev

# intake_screen.py imports ProfanityFree from guardrails.hub, which needs the
# validator package plus ./.guardrails/hub_registry.json (copied in at runtime).
# Installed with pip from public PyPI rather than `guardrails hub install`: the
# CLI fetches manifests from hub.api.guardrailsai.com, which no longer
# resolves, and validators no longer need an API key.
RUN /app/.venv/bin/python -m pip install --no-cache-dir guardrails-ai-profanity-free==0.1.0 \
    && /app/.venv/bin/python -c "import guardrails_ai.profanity_free"

# rag/rerank.py's HistoryMatchReranker loads this cross-encoder eagerly at
# app startup (build_agent_roster, called from api/main.py's lifespan)
# regardless of LLM/embedding provider. Pre-downloading it here means a
# pod never needs network access to huggingface.co to become ready.
ENV HF_HOME=/opt/hf-cache
RUN /app/.venv/bin/python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# ---- runtime ---- Start a new fresh environment
FROM python:${PYTHON_VERSION} AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /opt/hf-cache /app/.cache/huggingface
COPY --chown=app:app code_reviewer ./code_reviewer
COPY --chown=app:app code_reviewer/guardrails/hub_registry.json ./.guardrails/hub_registry.json
# Without an rc file guardrails defaults to remote inferencing and metrics, both
# of which call Guardrails' servers; this keeps validation local and tokenless.
RUN printf 'enable_metrics=false\nuse_remote_inferencing=false\n' > /home/app/.guardrailsrc \
    && chown app:app /home/app/.guardrailsrc
# api/logging_config.py creates ./logs relative to the working directory, and
# /app itself is root-owned, so the non-root user cannot create it at startup.
RUN mkdir /app/logs && chown app:app /app/logs

USER app