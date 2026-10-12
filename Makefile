.PHONY: check check-app jh api app up resume-worker

APP_DATABASE_URL ?= postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable

# The check the plan requires after every task.
check:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy jobhunt && uv run pytest -q

check-app:
	cd app && npm run typecheck && npm run lint && npm run build

# JSON API on 127.0.0.1:8765 against the local Docker database.
api:
	cd api && DATABASE_URL='$(APP_DATABASE_URL)' VAULT_BANK_PATH=/tmp/jobhunt-bank \
		uv run jobhunt serve --host 127.0.0.1 --port 8765

# Next.js board on 127.0.0.1:3000; it proxies /api to the API above.
app:
	cd app && npm run dev

# Usage: make jh ARGS="doctor"
# .env.tpl holds op:// references. .env holds local values (API key, vault path).
jh:
	cd api && op run --env-file=../.env.tpl --env-file=../.env -- uv run jobhunt $(ARGS)

# Local stack. op run injects secrets from .env.tpl and .env.
up:
	op run --env-file=.env.tpl --env-file=.env -- docker compose up -d --build

# Resume worker on the host, against the compose Postgres. Uses the same key injection.
resume-worker:
	cd api && op run --env-file=../.env.tpl --env-file=../.env -- env FIT_ALLOW_OFFSITE=1 \
		DATABASE_URL='$(APP_DATABASE_URL)' uv run jobhunt resume worker
