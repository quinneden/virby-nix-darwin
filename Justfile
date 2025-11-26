set working-directory := "pkgs/vm-runner"

default: help

help:
    @echo "Available commands:"
    @echo "    build          Build the Python package"
    @echo "    clean          Clean build artifacts and cache dirs"
    @echo "    format         Format code with ruff and isort"
    @echo "    help           Show this help message"
    @echo "    lint           Run linting checks"
    @echo "    type-check     Run mypy type checking"

[working-directory("../..")]
clean:
    @echo "Cleaning cache dirs..."
    @rm -rf dist build *.egg-info
    @find . -type d \
      -not -path "*/.venv/*" "(" \
        -name "*.egg-info" -or \
        -name ".*_cache" -or \
        -name "__pycache__" -or \
        -name "build" -or \
        -name "dist" -or \
        -name "result" \
      ")" -exec rm -rf {} + 2>/dev/null || true

format:
    @echo "Formatting code..."
    @uv run ruff format src/
    @uv run isort src/

lint:
    @echo "Running linting checks..."
    @uv run ruff check --fix src/
    @uv run isort --check-only --diff src/

type-check:
    @echo "Running type checks..."
    @uv run mypy

build:
    @echo "Building package..."
    @uv build

check: lint type-check
    @echo "All checks passed!"
