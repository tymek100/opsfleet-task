# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim@sha256:873f586f3794f52281bd039bf02c048a0be08fde619338f9941bad1eb6b34530 AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# Install project dependencies, never the repository package that includes evaluation code.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS runtime
ARG LOCAL_UID=10001
ARG LOCAL_GID=10001
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1 \
    DATA_DIR=/data GUI_STATIC_DIR=/app/web/dist RETAIL_RUNTIME_ENV_FILE=/run/secrets/runtime_env
RUN (getent group ${LOCAL_GID} || groupadd --gid ${LOCAL_GID} agent) \
    && useradd --uid ${LOCAL_UID} --gid ${LOCAL_GID} --no-create-home agent \
    && mkdir /data && chown ${LOCAL_UID}:${LOCAL_GID} /data
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=frontend /web/dist /app/web/dist
COPY src /app/src
COPY infra/workflow/entrypoint.py /app/entrypoint.py
USER agent
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).read()"]
ENTRYPOINT ["python", "/app/entrypoint.py"]
