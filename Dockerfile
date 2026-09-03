# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ARG NOVARIUSIRC_BUILD_COMMIT=""
ARG SOURCE_DATE_EPOCH=""

ENV POETRY_VERSION=2.4.1 \
    POETRY_EXPORT_VERSION=1.10.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/poetry && python -m venv /app/venv

RUN /opt/poetry/bin/pip install --upgrade pip && \
    /opt/poetry/bin/pip install \
        "poetry==$POETRY_VERSION" \
        "poetry-plugin-export==$POETRY_EXPORT_VERSION" && \
    /app/venv/bin/pip install --upgrade pip

COPY pyproject.toml poetry.lock README.md LICENSE ./
RUN /opt/poetry/bin/poetry export \
        -f requirements.txt \
        --output requirements.txt \
        --without-hashes && \
    /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY novariusirc ./novariusirc
COPY scripts ./scripts
RUN python scripts/generate_build_info.py --commit "$NOVARIUSIRC_BUILD_COMMIT" && \
    /app/venv/bin/pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install --no-install-recommends -y bzip3 && \
    rm -rf /var/lib/apt/lists/*

ARG NOVARIUSIRC_UID=10001
ARG NOVARIUSIRC_GID=10001

# Keep the container layout equivalent to a native install: /app/venv and
# /app/instances. Only /app/instances is persistent state.
COPY --from=builder /app/venv /app/venv
COPY config/config.example.toml /opt/novariusirc-instance-template/config/config.toml
COPY config/secrets.example.toml /opt/novariusirc-instance-template/config/secrets.toml
COPY config/feeds.example.toml /opt/novariusirc-instance-template/config/feeds.toml
COPY plugins /opt/novariusirc-instance-template/plugins
COPY scripts/container-entrypoint.sh /app/container-entrypoint

RUN addgroup --system --gid "$NOVARIUSIRC_GID" novariusirc && \
    adduser --system --uid "$NOVARIUSIRC_UID" --ingroup novariusirc --home /app novariusirc && \
    mkdir -p /app/instances/example && \
    cp -a /opt/novariusirc-instance-template/. /app/instances/example/ && \
    chmod 0755 /app/container-entrypoint && \
    chown -R novariusirc:novariusirc /app /opt/novariusirc-instance-template

USER novariusirc

STOPSIGNAL SIGINT

ENTRYPOINT ["/app/container-entrypoint"]
CMD []
