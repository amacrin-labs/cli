default:
    @just --list

# Run all checks (lint, test)
check: lint test

# Run tests
test *args:
    uv run pytest tests/ -v --tb=short {{ args }}

# Run tests with coverage
coverage:
    uv run pytest tests/ --cov=amacrin --cov-report=term-missing

# Lint and format check
lint:
    uv run ruff check amacrin/ tests/
    uv run ruff format --check amacrin/ tests/
    uv run ty check amacrin

# Auto-fix lint errors and format
fix:
    uv run ruff check amacrin/ tests/ --fix
    uv run ruff format amacrin/ tests/

# Build the package
build:
    uv build

# Clean build artifacts
clean:
    rm -rf dist/ build/ *.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Install in development mode
dev:
    uv sync
