.DEFAULT_GOAL := help
.PHONY: help install format lint typecheck test check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the project and development dependencies
	pip install -e ".[dev]"

format: ## Format the code and apply auto-fixable lint (ruff)
	ruff format src tests scripts
	ruff check --fix src tests scripts

lint: ## Check formatting and lint without modifying anything
	ruff format --check src tests scripts
	ruff check src tests scripts

typecheck: ## Check types (mypy)
	mypy

test: ## Run the test suite (pytest)
	pytest

check: lint typecheck test ## Run all checks (CI equivalent locally)

clean: ## Remove caches and build artifacts
	rm -rf .ruff_cache .mypy_cache .pytest_cache .coverage htmlcov coverage.xml build dist
	find . -type d -name '*.egg-info' -exec rm -rf {} +
	find . -type d -name __pycache__ -exec rm -rf {} +
