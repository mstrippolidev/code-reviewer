# syntax=docker/dockerfile:1.7
#
# CNPG needs pg_rewind/barman-cloud-wal-archive, which plain
# pgvector/pgvector doesn't ship — layer pgvector onto CNPG's own base
# image instead. Pin CNPG_BASE_TAG to a real released tag before building:
# https://github.com/cloudnative-pg/postgres-containers
ARG PG_MAJOR=16
ARG CNPG_BASE_TAG=${PG_MAJOR}-bookworm
FROM ghcr.io/cloudnative-pg/postgresql:${CNPG_BASE_TAG}

ARG PG_MAJOR=16

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends "postgresql-${PG_MAJOR}-pgvector" \
    && rm -rf /var/lib/apt/lists/*
USER postgres
