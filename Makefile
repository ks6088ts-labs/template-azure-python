# Git
GIT_REVISION ?= $(shell git rev-parse --short HEAD)
GIT_TAG ?= $(shell git describe --tags --abbrev=0 --always | sed -e s/v//g)

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
.DEFAULT_GOAL := help

.PHONY: info
info: ## show information
	@echo "GIT_REVISION: $(GIT_REVISION)"
	@echo "GIT_TAG: $(GIT_TAG)"

.PHONY: install-deps-dev
install-deps-dev: ## install dependencies for development
	uv sync --locked --all-groups
	uv run --locked prek install -f
	@which actionlint || echo "install actionlint https://github.com/rhysd/actionlint"

.PHONY: install-deps-ci
install-deps-ci: ## install dependencies for CI checks
	uv sync --locked --group dev

.PHONY: install-deps
install-deps: ## install dependencies for production
	uv sync --locked --no-dev

.PHONY: format-check
format-check: ## format check
	uv run --locked ruff format --check --verbose

.PHONY: format
format: ## format code
	uv run --locked ruff format --verbose

.PHONY: fix
fix: format ## apply auto-fixes
	uv run --locked ruff check --fix

.PHONY: lint
lint: ## lint
	uv run --locked ruff check .
	uv run --locked ty check
	uv run --locked pyrefly check
	actionlint
	uv run --locked zizmor --offline --strict-collection --min-severity high .

.PHONY: test
test: ## run tests
	uv run --locked pytest --capture=no -vv

.PHONY: hooks-check
hooks-check: ## check all configured hooks
	uv run --locked prek run --all-files

.PHONY: ci-test
ci-test: install-deps-ci format-check lint test ## run CI tests

.PHONY: update
update: ## update packages
	uv lock --upgrade

.PHONY: jupyterlab
jupyterlab: ## run Jupyter Lab
	uv run --locked --group notebook jupyter lab

# ---
# Docker
# ---
DOCKER_REPO_NAME ?= ks6088ts
DOCKER_IMAGE_NAME ?= template-python
DOCKER_COMMAND ?=

# Tools
HADOLINT_VERSION ?= v2.15.1
TRIVY_VERSION ?= 0.74.0
TRIVY_CACHE_VOLUME ?= template-python-trivy-cache

.PHONY: docker-build
docker-build: ## build Docker image
	docker build \
		-t $(DOCKER_REPO_NAME)/$(DOCKER_IMAGE_NAME):$(GIT_TAG) \
		--build-arg GIT_REVISION=$(GIT_REVISION) \
		--build-arg GIT_TAG=$(GIT_TAG) \
		.

.PHONY: docker-run
docker-run: ## run Docker container
	docker run --rm $(DOCKER_REPO_NAME)/$(DOCKER_IMAGE_NAME):$(GIT_TAG) $(DOCKER_COMMAND)

.PHONY: docker-lint
docker-lint: ## lint Dockerfile
	docker run --rm -i hadolint/hadolint:$(HADOLINT_VERSION) < Dockerfile

.PHONY: docker-scan
docker-scan: ## scan Docker image
	docker run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v $(TRIVY_CACHE_VOLUME):/root/.cache/trivy \
		aquasec/trivy:$(TRIVY_VERSION) image $(DOCKER_REPO_NAME)/$(DOCKER_IMAGE_NAME):$(GIT_TAG)

.PHONY: ci-test-docker
ci-test-docker: docker-lint docker-build docker-scan docker-run ## run CI test for Docker

# ---
# Docs
# ---

.PHONY: install-deps-docs
install-deps-docs: ## install dependencies for documentation
	uv sync --locked --no-dev --group docs

.PHONY: docs
docs: ## build documentation
	uv run --locked --no-dev --group docs mkdocs build

.PHONY: docs-serve
docs-serve: ## serve documentation
	uv run --locked --no-dev --group docs mkdocs serve

.PHONY: ci-test-docs
ci-test-docs: install-deps-docs docs ## run CI test for documentation
