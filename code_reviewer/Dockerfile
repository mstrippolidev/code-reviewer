# syntax=docker/dockerfile:1.7
ARG PYTHON_VERSION=3.12-slim

FROM python:${PYTHON_VERSION} AS builder

# speed up the installed process and reduce the weight of the packages
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*
# pinned so the resolver behaves identically on every build, not whatever
# Poetry happens to release the day this image is built
RUN curl -sSL https://install.python-poetry.org | python3 - --version ${POETRY_VERSION}
ENV PATH="${POETRY_HOME}/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
# install only production packages without the source code yet
RUN poetry install --no-root --only main --no-ansi

# rag/rerank.py's HistoryMatchReranker loads this cross-encoder eagerly at
# app startup (build_agent_roster, called from api/main.py's lifespan)
# regardless of LLM/embedding provider. Pre-downloading it here means a
# pod never needs network access to huggingface.co to become ready.
ENV HF_HOME=/opt/hf-cache
RUN poetry run python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

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

USER app