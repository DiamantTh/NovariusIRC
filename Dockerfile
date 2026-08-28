# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ENV POETRY_VERSION=2.4.1 \
    POETRY_EXPORT_VERSION=1.10.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip && \
    pip install "poetry==$POETRY_VERSION" "poetry-plugin-export==$POETRY_EXPORT_VERSION"

COPY pyproject.toml poetry.lock README.md ./
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes
RUN pip install --no-cache-dir -r requirements.txt

COPY novariusirc ./novariusirc
RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY config.example.toml ./config.example.toml
COPY config ./config

RUN addgroup --system app && \
    adduser --system --ingroup app --home /app app && \
    mkdir -p /app/logs && \
    chown -R app:app /app

USER app

ENTRYPOINT ["novariusirc"]
CMD ["--config", "/app/config.toml"]
