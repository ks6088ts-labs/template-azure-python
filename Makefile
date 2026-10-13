GIT_REVISION ?= $(shell git rev-parse --short HEAD)
GIT_TAG ?= $(shell git describe --tags --abbrev=0 --always | sed 's/^v//')
UV ?= uv
UV_VERSION = $(shell sed -n 's/^required-version = "==\(.*\)"/\1/p' pyproject.toml)

.DEFAULT_GOAL := help
.PHONY: help info install-deps-dev install-deps-ci install-deps format-check format fix check lint lint-python lint-workflows test
.PHONY: test-eval lint-eval typecheck-compare hooks-check ci-test update jupyterlab
.PHONY: docker-build docker-run docker-smoke-test docker-lint docker-scan ci-test-docker
.PHONY: install-deps-docs docs docs-serve ci-test-docs build smoke-test init-template

help: ## show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

info: ## show Git information
	@echo "GIT_REVISION: $(GIT_REVISION)"
	@echo "GIT_TAG: $(GIT_TAG)"
	@echo "UV_VERSION: $(UV_VERSION)"

install-deps-dev: ## install development dependencies and all optional integrations
	$(UV) sync --locked --all-extras --group dev --group docs
	$(UV) run --locked --all-extras --group dev prek install -f

install-deps-ci: ## install CI dependencies and all optional integrations
	$(UV) sync --locked --all-extras --group dev

install-deps: ## install only production dependencies
	$(UV) sync --locked --no-default-groups

format-check: ## check formatting
	$(UV) run --locked --all-extras --group dev ruff format --check .

format: ## format code
	$(UV) run --locked --all-extras --group dev ruff format .

fix: format ## apply lint fixes
	$(UV) run --locked --all-extras --group dev ruff check --fix .

lint: lint-python lint-workflows ## run Python and workflow quality gates

check: format-check lint-python ## check Python formatting, typing, linting, and architecture

lint-python: ## run the canonical Python quality gates (mypy, Ruff, architecture)
	$(UV) run --locked --all-extras --group dev ruff check .
	$(UV) run --locked --all-extras --group dev mypy
	$(UV) run --locked --all-extras --group dev lint-imports

ACTIONLINT_VERSION ?= 1.7.12
lint-workflows: ## lint workflows with native actionlint or its pinned Docker fallback
	@if command -v actionlint >/dev/null 2>&1; then \
		actionlint; \
	elif command -v docker >/dev/null 2>&1; then \
		docker run --rm -v "$(CURDIR):/repo:ro" -w /repo rhysd/actionlint:$(ACTIONLINT_VERSION); \
	else \
		echo "Install actionlint $(ACTIONLINT_VERSION) or Docker to lint workflows." >&2; exit 1; \
	fi
	$(UV) run --locked --all-extras --group dev zizmor --offline --strict-collection --min-severity high .github/workflows

test: ## run offline tests with concise captured output
	$(UV) run --locked --all-extras --group dev pytest -q

EVAL_ARGS ?=
test-eval: ## run paid local Foundry evaluations explicitly (EVAL_ARGS='-m llm_eval_smoke')
	env -u CONFIDENT_API_KEY \
		DEEPEVAL_TELEMETRY_OPT_OUT=1 DEEPEVAL_DISABLE_DOTENV=1 DEEPEVAL_DISABLE_LEGACY_KEYFILE=1 \
		DEEPEVAL_EVAL_MODE=llm DEEPEVAL_MODE=stable CONFIDENT_OPEN_BROWSER=0 \
		DEEPEVAL_RETRY_MAX_ATTEMPTS=2 DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE=60 \
		DEEPEVAL_RESULTS_FOLDER=artifacts/evaluations \
		$(UV) run --locked --all-extras --no-default-groups --group eval deepeval test run tests/evaluations \
		--run-llm-evals --override-ini='addopts=-ra --strict-markers' --override-ini='log_cli=false' \
		--capture=fd --junitxml=artifacts/evaluations/junit.xml $(EVAL_ARGS)

lint-eval: ## compare optional type checkers on the existing evaluation tests
	$(UV) run --locked --all-extras --group eval --group type-eval ty check tests/evaluations tests/test_evaluation_deepeval.py
	$(UV) run --locked --all-extras --group eval --group type-eval pyrefly check tests/evaluations tests/test_evaluation_deepeval.py

typecheck-compare: ## evaluate alternative type checkers without changing the required mypy gate
	$(UV) run --locked --all-extras --group type-eval ty check
	$(UV) run --locked --all-extras --group type-eval pyrefly check

hooks-check: ## check all configured hooks
	$(UV) run --locked --all-extras --group dev prek run --all-files

ci-test: install-deps-ci format-check lint test ## run CI checks

update: ## update dependency locks (review advisories before committing)
	$(UV) lock --upgrade

build: ## build an installable wheel and source distribution
	$(UV) build

jupyterlab: ## run Jupyter Lab
	$(UV) run --locked --all-extras --group notebook jupyter lab

smoke-test: ## probe health and readiness without mutating application data
	$(UV) run --locked --no-default-groups python -m scripts.smoke_test $(SMOKE_ARGS)

init-template: ## preview metadata customization (INIT_ARGS='--name my-service --apply' to write)
	$(UV) run --locked --no-default-groups python -m scripts.init_template $(INIT_ARGS)

DOCKER_REPO_NAME ?= ks6088ts
DOCKER_IMAGE_NAME ?= template-azure-python
DOCKER_IMAGE = $(DOCKER_REPO_NAME)/$(DOCKER_IMAGE_NAME):$(GIT_TAG)
HADOLINT_VERSION ?= v2.15.1
TRIVY_VERSION ?= 0.74.0
TRIVY_DIGEST ?= sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
TRIVY_CACHE_VOLUME ?= template-azure-python-trivy-cache

docker-build: ## build the minimal production image
	docker build -t $(DOCKER_IMAGE) --build-arg GIT_REVISION=$(GIT_REVISION) --build-arg GIT_TAG=$(GIT_TAG) .

docker-run: ## run a non-root, read-only container on loopback
	docker run --rm --read-only --cap-drop=ALL --security-opt=no-new-privileges \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m -p 127.0.0.1:8000:8000 $(DOCKER_IMAGE)

docker-smoke-test: ## check the production image with read-only health probes
	@set -eu; \
	container=$$(docker run -d --read-only --cap-drop=ALL --security-opt=no-new-privileges \
		--tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m -p 127.0.0.1::8000 $(DOCKER_IMAGE)); \
	trap 'docker rm -f "$$container" >/dev/null' EXIT; \
	port=$$(docker port "$$container" 8000/tcp | sed 's/.*://'); \
	$(UV) run --locked --no-default-groups python -m scripts.smoke_test --base-url "http://127.0.0.1:$$port" \
		|| { docker logs "$$container"; exit 1; }

docker-lint: ## lint the Dockerfile
	docker run --rm -i hadolint/hadolint:$(HADOLINT_VERSION) < Dockerfile

docker-scan: ## scan an image archive without sharing the Docker socket
	@set -eu; mkdir -p artifacts; \
	archive="$(CURDIR)/artifacts/image-scan.tar"; \
	trap 'rm -f "$$archive"' EXIT; \
	docker save --output "$$archive" $(DOCKER_IMAGE); \
	docker run --rm -v "$$archive:/scan/image.tar:ro" -v $(TRIVY_CACHE_VOLUME):/root/.cache/trivy \
		aquasec/trivy:$(TRIVY_VERSION)@$(TRIVY_DIGEST) image --input /scan/image.tar --scanners vuln \
		--db-repository ghcr.io/aquasecurity/trivy-db:2 \
		--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1

ci-test-docker: docker-lint docker-build docker-scan docker-smoke-test ## validate the production container

install-deps-docs: ## install documentation dependencies
	$(UV) sync --locked --no-default-groups --group docs

docs: ## build documentation with warnings treated as errors
	$(UV) run --locked --no-default-groups --group docs mkdocs build --strict

docs-serve: ## serve documentation
	$(UV) run --locked --no-default-groups --group docs mkdocs serve

ci-test-docs: install-deps-docs docs ## run documentation CI checks
