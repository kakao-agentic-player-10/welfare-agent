# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS db-seed

ARG WELFARE_DB_GZ_URL=https://github.com/kakao-agentic-player-10/welfare-agent/releases/download/db-2026-06-29/welfare-agent.db.gz

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /seed \
    && curl -fsSL "${WELFARE_DB_GZ_URL}" -o /tmp/welfare-agent.db.gz \
    && gzip -dc /tmp/welfare-agent.db.gz > /seed/welfare-agent.db \
    && test -s /seed/welfare-agent.db \
    && rm -f /tmp/welfare-agent.db.gz

FROM python:${PYTHON_VERSION}-slim AS app

# Non-secret. If a deploy target cannot inject runtime env vars, set this ARG default
# to the public embedding proxy URL before building the image.
ARG OPENAI_EMBEDDING_PROXY_URL=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    OPENAI_EMBEDDING_PROXY_URL=${OPENAI_EMBEDDING_PROXY_URL}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY main.py ./

RUN uv sync --frozen --no-dev

RUN mkdir -p /app/data
COPY --from=db-seed /seed/welfare-agent.db /app/data/welfare-agent.db

EXPOSE 8000

CMD ["python", "main.py"]
