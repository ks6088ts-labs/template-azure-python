FROM python:3.13-slim-bookworm AS requirements-stage

WORKDIR /build

COPY --from=astral/uv:0.12.19 /uv /usr/local/bin/uv

COPY ./pyproject.toml ./uv.lock ./

RUN uv export --locked --format requirements-txt --no-dev --no-hashes --no-emit-project --output-file requirements.txt

FROM python:3.13-slim-bookworm

ARG GIT_REVISION="0000000"
ARG GIT_TAG="x.x.x"

WORKDIR /app

# Copy requirements first for better cache efficiency
COPY --from=requirements-stage /build/requirements.txt /app/requirements.txt

# Install dependencies in a separate layer for caching
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# Copy application code after dependencies are installed
COPY . .

CMD ["python", "-m", "template_python.core"]
