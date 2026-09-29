.PHONY: install lint format typecheck test check up down logs ps config

install:        ## Install dependencies
	uv sync

lint:           ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

format:         ## Auto-fix lint and format
	uv run ruff check --fix .
	uv run ruff format .

typecheck:      ## Strict type check
	uv run mypy src

test:           ## Unit tests
	uv run pytest -m "not integration"

check: lint typecheck test   ## Everything CI runs

up:             ## Start the stack (file set chosen by COMPOSE_FILE in .env)
	docker compose up -d --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

config:         ## Validate compose files
	docker compose config -q
