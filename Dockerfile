# syntax=docker/dockerfile:1

# Not Alpine: onnxruntime (fastembed, meaning search) has no musl wheel, so it cannot install there.

# ---- build: resolve the locked dependencies into /app/.venv with uv ----
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /bin/uv

# Byte-compile for faster start-up; copy (not hardlink) out of the cache mount;
# use the image's Python instead of downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Website dependencies only by default. For an image that can also run the data tools
# (machine_draft, import_english, export_dataset, push_hf):  docker build --build-arg UV_GROUPS=--all-groups .
ARG UV_GROUPS=--no-default-groups

# Dependencies only: this layer is rebuilt only when pyproject.toml or uv.lock change,
# and the uv cache mount keeps downloaded wheels between builds.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project $UV_GROUPS

# ---- runtime: slim image with just the venv and the app (no uv, no build cache) ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_DEBUG=0 \
    FASTEMBED_CACHE_PATH=/models/fastembed \
    HF_HOME=/models/hf

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY deploy/entrypoint.sh /entrypoint.sh
COPY . .

RUN chmod +x /entrypoint.sh \
 && python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
