.PHONY: format lint syntax test quality install-hooks

PY_SCRIPTS=skills/distill-knowledge/scripts

format:
	uvx ruff format $(PY_SCRIPTS)

lint:
	uvx ruff check $(PY_SCRIPTS)

syntax:
	python3 -m compileall -q $(PY_SCRIPTS)

test:
	uvx pytest

quality:
	uvx ruff format --check $(PY_SCRIPTS)
	uvx ruff check $(PY_SCRIPTS)
	python3 -m compileall -q $(PY_SCRIPTS)
	uvx pytest

install-hooks:
	uv tool install pre-commit
	pre-commit install
