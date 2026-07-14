# Ciel Agent Framework — official image
# Multi-stage build with uv. Installs the gateway + acp extras and runs the
# composed gateway (control + MCP host + webhook) via the `ciel serve` CLI.
#
# Build:   docker build -t ciel:0.1.0 .
# Run:     docker run -p 8080:8080 -e CIEL_TENANT=acme ciel:0.1.0
# The gateway does NOT require a remote LLM: with no CIEL_PROVIDER_URL it boots
# an offline echo provider so health/tool endpoints stay reachable.

FROM python:3.12-slim AS builder
LABEL org.opencontainers.image.source="https://github.com/ciel-agent-framework/ciel"
LABEL org.opencontainers.image.license="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install only what is needed to resolve the lock, then sync project + extras.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra gateway --extra acp

COPY src/ ./src/
COPY README.md CHANGELOG.md ./

RUN uv sync --frozen --no-dev --extra gateway --extra acp

FROM python:3.12-slim AS runtime
LABEL org.opencontainers.image.title="ciel"
LABEL org.opencontainers.image.description="Ciel Agent Framework — enterprise multi-agent harness gateway"
LABEL org.opencontainers.image.license="AGPL-3.0-or-later"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    CIEL_TENANT="acme"

RUN groupadd -r ciel && useradd -r -g ciel -d /app -s /sbin/nologin ciel

WORKDIR /app

COPY --from=builder /app /app
COPY --from=builder /app/.venv /app/.venv

# Audit log volume (JSONL per session/tenant).
RUN mkdir -p /var/lib/ciel/audit && chown -R ciel:ciel /var/lib/ciel
VOLUME ["/var/lib/ciel/audit"]

RUN chown -R ciel:ciel /app
USER ciel

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8080/health').status_code==200 else 1)"

ENTRYPOINT ["ciel", "serve", "--host", "0.0.0.0", "--port", "8080"]
