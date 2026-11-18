# syntax=docker/dockerfile:1.7
ARG BASE_IMAGE=code-reviewer-base:latest
FROM ${BASE_IMAGE} AS runtime

USER root
WORKDIR /app

COPY --chown=app:app mcp_server ./mcp_server

USER app

EXPOSE 8001

CMD ["python", "-m", "mcp_server.server"]
