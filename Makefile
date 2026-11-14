.PHONY: install api worker simulator bootstrap preflight seed test lint format check build

install:
	uv sync --locked --group dev

api:
	uv run chainlex-api

worker:
	uv run chainlex-worker

simulator:
	uv run chainlex-simulator

bootstrap:
	uv run chainlex-db bootstrap

preflight:
	uv run chainlex-db preflight

seed:
	uv run chainlex-db seed-demo

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

check: lint test

build:
	uv build
