.PHONY: install lint format typecheck test test-integration check up down logs ps config walkthrough demo eval ingest-kb seed metrics

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

test-integration: ## Integration tests (needs `make up` and `make seed`)
	uv run pytest -m integration

check: lint typecheck test   ## Everything CI runs

up:             ## Start the stack (file set chosen by COMPOSE_FILE in .env)
	docker compose up -d --build --wait

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

ps:
	docker compose ps

config:         ## Validate compose files
	docker compose config -q

walkthrough:    ## Send real events through the running stack and check the outcomes
	scripts/walkthrough.sh

demo:           ## The §30 demo: mismatch → investigation → AI report → approve; worker kill + recovery
	scripts/walkthrough.sh demo

eval:           ## Run the AI evaluation scenarios through the running stack (eval/)
	uv run python eval/run_eval.py

ingest-kb:      ## Re-index knowledge_base/ (only changed documents are re-embedded)
	docker compose run --rm --build kb-ingest

seed:           ## Issue fresh API keys (one per role per tenant) into .api-keys.json
	docker compose run --rm --no-deps -T api python -m sentinel.seed > .api-keys.json
	@echo "API keys written to .api-keys.json (gitignored)"

metrics:        ## Show business metrics from the API and every worker
	scripts/metrics.sh
