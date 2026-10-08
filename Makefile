.PHONY: check check-web jh api web

APP_DATABASE_URL ?= postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable

# The check the plan requires after every task.
check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy jobhunt
	uv run pytest -q

check-web:
	cd web && npm run typecheck && npm run lint && npm run build

# JSON API on 127.0.0.1:8765 against the local Docker database.
api:
	DATABASE_URL='$(APP_DATABASE_URL)' VAULT_BANK_PATH=/tmp/jobhunt-bank \
		uv run jobhunt serve --host 127.0.0.1 --port 8765

# Next.js board on 127.0.0.1:3000; it proxies /api to the API above.
web:
	cd web && npm run dev

# Usage: make jh ARGS="doctor"
jh:
	op run --env-file=.env.tpl -- uv run jobhunt $(ARGS)
