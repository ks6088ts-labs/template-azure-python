FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build

COPY --from=ghcr.io/astral-sh/uv@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-default-groups --no-install-project

COPY template_azure_python/ template_azure_python/
RUN uv sync --locked --no-default-groups --no-editable

FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS runtime

ARG GIT_REVISION="0000000"
ARG GIT_TAG="x.x.x"

LABEL org.opencontainers.image.revision="${GIT_REVISION}" \
      org.opencontainers.image.version="${GIT_TAG}"

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION="${GIT_TAG}" \
    APP_REVISION="${GIT_REVISION}" \
    HOST=0.0.0.0 \
    PORT=8000 \
    HOME=/app

RUN rm -rf /usr/local/lib/python3.14/site-packages/pip \
        /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
        /usr/local/lib/python3.14/ensurepip \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14 \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY LICENSE /app/LICENSE
USER 10001:10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import http.client; c=http.client.HTTPConnection('127.0.0.1',8000,timeout=3); c.request('GET','/healthz'); r=c.getresponse(); raise SystemExit(0 if r.status==200 else 1)"]

ENTRYPOINT ["python", "-m", "template_azure_python"]
