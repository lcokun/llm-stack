# llm-stack — single entry point across uv, go, cargo and npm.
# Recipes run under sh, not fish, so they also work on CI runners.

# Show available recipes.
default:
    @just --list

# Validate the OpenAPI contract and the Python sources.
lint:
    uv run --with openapi-spec-validator==0.9.0 openapi-spec-validator api/openapi.yaml
    cd services/core && uv run ruff check .
    cd services/core && uv run ruff format --check .

# Format the Python sources in place.
fmt:
    cd services/core && uv run ruff format .
    cd services/core && uv run ruff check --fix .


# Run the python test suite.
test:
    cd services/core && uv run pytest

# Start the development stack.
dev:
    docker compose up -d

# Stop the development stack.
down:
    docker compose down

# Apply pending database migrations.
migrate:
    dbmate --migrations-dir db/migrations up