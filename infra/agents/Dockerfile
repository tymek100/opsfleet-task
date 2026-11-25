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
    uv sync --no-dev --no-install-project --group evaluation

FROM python:3.12-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64 AS runtime
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATA_DIR=/data RETAIL_RUNTIME_ENV_FILE=/run/secrets/model_env
RUN groupadd --gid 10001 agent && useradd --uid 10001 --gid agent --no-create-home agent \
    && mkdir /data && chown agent:agent /data
COPY --from=dependencies /app/.venv /app/.venv
COPY src /app/src
COPY infra/agents/entrypoint.py /app/entrypoint.py
USER agent
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=45s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/.well-known/agent-card.json', timeout=2).read()"]
ENTRYPOINT ["python", "/app/entrypoint.py"]

FROM runtime AS retail
ENV RETAIL_AGENT_ROLE=retail
CMD ["--role", "retail", "--port", "8000"]

FROM runtime AS inventory
ENV RETAIL_AGENT_ROLE=inventory
CMD ["--role", "inventory", "--port", "8000"]

FROM runtime AS distribution
ENV RETAIL_AGENT_ROLE=distribution
CMD ["--role", "distribution", "--port", "8000"]

FROM runtime AS coordinator
ENV RETAIL_AGENT_ROLE=coordinator
CMD ["--role", "coordinator", "--port", "8000"]

FROM runtime AS gui
COPY --from=frontend /web/dist /app/web/dist
ENTRYPOINT ["python", "-m", "retail_insight.interfaces.gui"]
CMD []
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]

FROM runtime AS inspector-gui
ENTRYPOINT ["python", "-m", "retail_insight.interfaces.inspector"]
CMD []
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()"]
