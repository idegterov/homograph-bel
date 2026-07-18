.PHONY: setup format check build

setup:
	uv sync --frozen
	uv run pre-commit install

format:
	uv run ruff format
	uv run ruff check --fix

check:
	uv lock --check
	uv run ruff format --check
	uv run ruff check
	uv run pyright
	uv run pytest

build:
	uv build
