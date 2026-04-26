VENV     := .venv
PYTHON   := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip
PYTEST   := $(VENV)/bin/pytest

CONTAINER_RUNTIME := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
IMAGE := lightspeed-agentic-sandbox:latest

.PHONY: venv install install-all test lint format eval eval-report image clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

venv: ## Create virtual environment
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv ## Install package in editable mode with dev deps
	$(PIP) install -e ".[dev]"

install-all: venv ## Install with all provider SDKs + dev + eval deps
	$(PIP) install -e ".[all,dev,eval]"

test: ## Run unit tests
	$(PYTEST) tests/ -v

lint: ## Run ruff linter
	$(VENV)/bin/ruff check src/ tests/ evals/

format: ## Auto-format with ruff
	$(VENV)/bin/ruff format src/ tests/ evals/
	$(VENV)/bin/ruff check --fix src/ tests/ evals/

image: ## Build production container image
	$(CONTAINER_RUNTIME) build -t $(IMAGE) .

EVAL_ARGS ?=

GCLOUD_ADC := $(HOME)/.config/gcloud/application_default_credentials.json
GCLOUD_MOUNT := $(shell test -f $(GCLOUD_ADC) && echo "-v $(GCLOUD_ADC):/tmp/gcloud-adc.json:ro,Z -e GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcloud-adc.json")

define RUN_EVAL
	$(CONTAINER_RUNTIME) run --rm \
		-v $(CURDIR)/evals:/app/evals:Z \
		$(GCLOUD_MOUNT) \
		-e ANTHROPIC_API_KEY \
		-e CLAUDE_CODE_USE_VERTEX \
		-e ANTHROPIC_VERTEX_PROJECT_ID \
		-e CLOUD_ML_REGION \
		-e GOOGLE_API_KEY \
		-e GEMINI_API_KEY \
		-e OPENAI_API_KEY \
		-e OPENAI_BASE_URL \
		-e AWS_ACCESS_KEY_ID \
		-e AWS_SECRET_ACCESS_KEY \
		-e AWS_REGION \
		$(IMAGE) \
		python -m pytest evals/ -v $(1)
endef

eval: image ## Run evals in container (use EVAL_ARGS to filter, e.g. EVAL_ARGS="-k claude")
	$(call RUN_EVAL,$(EVAL_ARGS))

eval-report: image ## Run evals in container and generate JSON report
	$(call RUN_EVAL,--eval-report=evals/report.json $(EVAL_ARGS))

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
