# Thin wrapper over the CLI, mainly for CI on Linux. On Windows run the
# commands directly: uv run alpinehydro <command>.

.PHONY: sync lint test demo check all

sync:
	uv sync --locked

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

demo:
	uv run alpinehydro demo

check:
	uv run alpinehydro check-repo

all: sync lint test demo check
