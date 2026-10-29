# Convenience targets for Linux and macOS. On Windows use the `querydoctor` CLI directly.
.PHONY: install seed bench serve test lint format typecheck check clean

install:
	python -m pip install -e ".[dev]"

seed:
	querydoctor seed

bench:
	querydoctor bench

serve:
	querydoctor serve

test:
	pytest --cov

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml htmlcov build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
