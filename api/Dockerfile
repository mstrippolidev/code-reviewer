# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=code-reviewer-base:latest
FROM ${BASE_IMAGE} AS runtime

# builder stage already ran as root in the base image's own build;
# switch back briefly to copy files with correct ownership.
USER root
WORKDIR /app

COPY --chown=app:app api ./api
COPY --chown=app:app alembic.ini ./alembic.ini

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/health/').status_code==200 else 1)"

# Single process, single worker — don't add --workers.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
