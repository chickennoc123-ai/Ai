# ---------------------------------------------------------------------------
# EA Factory Pro - developer shortcuts
# ---------------------------------------------------------------------------
.PHONY: help install env up down logs ps restart api worker dashboard init-db seed pipeline test lint clean

PYTHON ?= python3

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	$(PYTHON) -m pip install -r requirements.txt

env: ## Create .env from the template
	@test -f .env || cp .env.example .env
	@echo ".env ready"

up: env ## Start the whole stack with Docker
	docker-compose up -d --build
	@echo "Dashboard : http://localhost:8501"
	@echo "API docs  : http://localhost:8000/docs"

down: ## Stop the stack
	docker-compose down

clean-volumes: ## Stop the stack and delete the volumes (destructive)
	docker-compose down -v

logs: ## Follow all container logs
	docker-compose logs -f

ps: ## Show container status
	docker-compose ps

restart: ## Restart the API and the worker
	docker-compose restart api worker

api: ## Run the API locally
	uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run the agent worker locally
	$(PYTHON) -m worker.main

dashboard: ## Run the dashboard locally
	streamlit run dashboard/app.py

init-db: ## Create the database schema
	$(PYTHON) scripts/init_db.py

seed: ## Seed strategies, candles and a demo account
	$(PYTHON) scripts/seed_data.py --backtest

pipeline: ## Run the research pipeline end to end
	$(PYTHON) scripts/run_pipeline.py

test: ## Run the test suite
	$(PYTHON) -m pytest -q

test-verbose: ## Run the test suite with output
	$(PYTHON) -m pytest -v

clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf .coverage htmlcov
