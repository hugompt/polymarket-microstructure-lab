# polymarket-microstructure-lab convenience runner.
# Run every target from THIS directory (the project root). It always uses the project's
# virtualenv, so you never need a bare `python` on your PATH.
#
#   make install     one-time: create the venv + install backend & frontend deps
#   make setup       one-time: create the DB schema + discover live markets
#   make api         TERMINAL 1: backend API   -> http://localhost:8000
#   make dashboard   TERMINAL 2: the dashboard -> http://localhost:3000
#   make paper       TERMINAL 3 (optional): a long live paper-trading session
#   make analyze     print the skeptical wallet PnL report
#   make test        run the backend test suite
#   make collect     optional: record orderbook history (research/backtest side only)
#
# api, dashboard, paper and collect are LONG-RUNNING: each needs its OWN terminal window.
# setup, analyze and test finish and return you to the prompt.

SHELL := /bin/bash
PY := backend/.venv/bin/python
# Absolute DB path so every target uses the same database regardless of directory.
export PML_DATABASE_URL := sqlite:///$(CURDIR)/backend/polymarket_lab.db

.DEFAULT_GOAL := help

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  make %-11s %s\n", $$1, $$2}'

install: ## one-time: create the Python venv + install backend & frontend deps
	python3 -m venv backend/.venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm install
	@echo ">> install done. Next: 'cp .env.example .env' and set PML_TARGET_WALLET, then 'make setup'."

setup: ## one-time: migrate the DB and discover current live markets
	cd backend && .venv/bin/alembic upgrade head
	$(PY) -m app discover
	@echo ">> setup done. Now run 'make api' (terminal 1) and 'make dashboard' (terminal 2)."

api: ## TERMINAL 1: backend API on http://localhost:8000 (required for the dashboard)
	$(PY) -m app serve

dashboard: ## TERMINAL 2: the dashboard on http://localhost:3000
	cd frontend && npm install && npm run dev

paper: ## TERMINAL 3 (optional): a 4-hour live paper session (stale_odds). Ctrl-C to stop early.
	$(PY) -m app paper-trade --strategy stale_odds --latencies 0,40,100,250,500,1000 --duration 14400

collect: ## optional: record orderbook/tick history for backtests, replay and data-quality
	$(PY) -m app collect --assets BTC,ETH,SOL,XRP,DOGE --windows 5,15

sync-wallet: ## pull the target bot wallet's public history
	$(PY) -m app sync-wallet

analyze: ## print the skeptical wallet PnL report (backfills + enriches first)
	$(PY) -m app analyze-wallet

test: ## run the backend test suite
	cd backend && .venv/bin/python -m pytest -q

stop: ## stop the backend API (:8000) and the collector (leaves the dashboard running)
	@PIDS=$$(lsof -ti:8000 2>/dev/null); if [ -n "$$PIDS" ]; then kill $$PIDS && echo "stopped backend on :8000"; else echo ":8000 already free"; fi
	@pkill -f "app collect" 2>/dev/null && echo "stopped collector" || echo "no collector running"

restart-api: ## free :8000 (stop the old backend) and start a fresh one
	@PIDS=$$(lsof -ti:8000 2>/dev/null); if [ -n "$$PIDS" ]; then kill $$PIDS && echo "stopped old backend on :8000"; sleep 1; fi
	$(PY) -m app serve
