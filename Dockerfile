FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY padel_bot ./padel_bot
COPY venues.yaml README.md ./
RUN uv sync --frozen --no-dev

# Runs as root on purpose: Fly.io volumes (stats database in /data) are mounted root-owned.
RUN mkdir -p /data

CMD ["/app/.venv/bin/padel-bot"]
