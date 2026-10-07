# llm-stack — single entry point across uv, go, cargo and npm.
# Recipes run under sh, not fish, so they also work on CI runners.

set dotenv-load := true

# Show available recipes.
default:
    @just --list

# Everything CI runs.
check: lint test test-go

# Type-check the Python sources.
typecheck:
    uv run --project services/core pyright

# Validate the OpenAPI contract and the Python sources.
lint:
    uv run --with openapi-spec-validator==0.9.0 openapi-spec-validator api/openapi.yaml
    cd services/core && uv run ruff check .
    cd services/core && uv run ruff format --check .
    uv run --project services/core pyright
    cd services/gateway && test -z "$(gofmt -l . | tee /dev/stderr)"
    cd services/gateway && go vet ./...

# Format the Python and Go sources in place.
fmt:
    cd services/core && uv run ruff format .
    cd services/core && uv run ruff check --fix .
    cd services/gateway && go fmt ./...

# Run the python test suite. Extra arguments go to pytest.
test *args:
    cd services/core && uv run pytest {{args}}

# Run the Go test suite.
test-go:
    cd services/gateway && go test ./...

# Run the gateway in the foreground.
gateway:
    cd services/gateway && go run .

# Start the development stack.
dev:
    docker compose up -d

# Stop the development stack.
down:
    docker compose down

#  Run the API in the foreground against the dev database.
serve:
    cd services/core && uv run uvicorn llm_stack_api.app:app --port 8000 --reload

# Apply pending database migrations.
migrate:
    dbmate --migrations-dir db/migrations up