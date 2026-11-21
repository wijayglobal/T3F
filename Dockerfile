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

# Unprivileged account for the web server. The entrypoint starts as root only to fix the
# ownership of the models volume, then drops to this user (setpriv) before running gunicorn.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /models \
 && chown app:app /models

COPY --from=builder /app/.venv /app/.venv
COPY deploy/entrypoint.sh /entrypoint.sh
COPY . .

# collectstatic needs settings to load; the key is a throwaway used only during the build.
RUN chmod +x /entrypoint.sh \
 && DJANGO_SECRET_KEY=collectstatic-build-only-not-used-at-runtime-0123456789abcdef \
    python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
