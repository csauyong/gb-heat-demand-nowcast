.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := 3.11

.PHONY: help setup lint fmt test check clean data-check

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the venv and install the package + dev tools (editable)
	uv venv --python $(PY)
	uv pip install -e ".[dev]"
	@echo
	@echo "Activate with: source .venv/bin/activate"
	@echo "Then run 'make lint' and 'make test'."

lint:  ## ruff check + ruff format --check + mypy
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

fmt:  ## Auto-fix lint and format
	uv run ruff check --fix src tests
	uv run ruff format src tests

test:  ## Run the test suite with coverage
	uv run pytest --cov --cov-report=term-missing

check: lint test data-check  ## Everything CI would run

data-check:  ## Fail if any data file has been committed (CLAUDE.md hard rule)
	@tracked=$$(git ls-files data/ | grep -v '\.gitkeep$$' || true); \
	if [ -n "$$tracked" ]; then \
		echo "ERROR: data files are tracked in git:"; echo "$$tracked"; exit 1; \
	else \
		echo "OK: no data files tracked."; \
	fi

clean:  ## Remove caches and build artefacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
