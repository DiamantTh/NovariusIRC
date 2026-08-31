# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ARG NOVARIUSIRC_BUILD_COMMIT=""
ARG SOURCE_DATE_EPOCH=""

ENV POETRY_VERSION=2.4.1 \
    POETRY_EXPORT_VERSION=1.10.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/poetry && python -m venv /opt/venv

RUN /opt/poetry/bin/pip install --upgrade pip && \
    /opt/poetry/bin/pip install \
        "poetry==$POETRY_VERSION" \
        "poetry-plugin-export==$POETRY_EXPORT_VERSION" && \
    /opt/venv/bin/pip install --upgrade pip

COPY pyproject.toml poetry.lock README.md LICENSE ./
RUN /opt/poetry/bin/poetry export \
        -f requirements.txt \
        --output requirements.txt \
        --without-hashes && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY novariusirc ./novariusirc
COPY scripts ./scripts
RUN python scripts/generate_build_info.py --commit "$NOVARIUSIRC_BUILD_COMMIT" && \
    /opt/venv/bin/pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY config.example.toml ./config.example.toml
COPY config ./config
COPY plugins ./plugins

RUN addgroup --system app && \
    adduser --system --ingroup app --home /app app && \
    mkdir -p /app/logs /app/data && \
    chown -R app:app /app

USER app

STOPSIGNAL SIGINT

ENTRYPOINT ["novariusirc"]
CMD ["--config", "/app/config.toml"]
