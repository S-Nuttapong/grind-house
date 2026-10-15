.PHONY: check check-app check-node jh api app dev kill-ports up resume-worker pg-dump

APP_DATABASE_URL ?= postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable
TEST_DATABASE_URL ?= postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt_test?sslmode=disable
# Postgres.app lives in ~/Applications: /Applications is not writable on this Mac.
PG_BIN := $(HOME)/Applications/Postgres.app/Contents/Versions/16/bin
DEV_PORTS := 8765 3000
# app/.nvmrc pins the arm64 Node. /usr/local/bin/node is v26 x64 and removes
# the matching @next/swc binary whenever npm install runs under it.
NODE_VERSION := $(shell cat app/.nvmrc)
NODE_BIN := $(HOME)/.nvm/versions/node/v$(NODE_VERSION)/bin
WITH_NODE = PATH="$(NODE_BIN):$$PATH"

# The check the plan requires after every task.
# Tests use jobhunt_test on the Postgres.app server (this project only).
check:
	cd api && TEST_DATABASE_URL='$(TEST_DATABASE_URL)' uv run ruff check . && uv run ruff format --check . && uv run mypy jobhunt && uv run pytest -q

check-node:
	@test -x "$(NODE_BIN)/node" || { echo "missing Node $(NODE_VERSION); run: nvm install $(NODE_VERSION)"; exit 1; }

check-app: check-node
	cd app && $(WITH_NODE) && npm run typecheck && npm run lint && npm run build

# JSON API on 127.0.0.1:8765 against the Postgres.app database (jobhunt-16).
api:
	set -a; . ./.env; set +a; cd api && env JOBHUNT_ALLOW_OFFSITE=1 \
		DATABASE_URL='$(APP_DATABASE_URL)' VAULT_BANK_PATH=/tmp/jobhunt-bank \
		uv run --extra claude jobhunt serve --host 127.0.0.1 --port 8765

# Next.js board on 127.0.0.1:3000; it proxies /api to the API above.
app: check-node
	cd app && $(WITH_NODE) && npm run dev

# Stops whatever listens on the dev ports. Sends TERM first, then KILL if still alive.
kill-ports:
	@for port in $(DEV_PORTS); do \
		pids=$$(lsof -nP -ti tcp:$$port -sTCP:LISTEN); \
		if [ -n "$$pids" ]; then echo "port $$port: stopping $$pids"; kill $$pids || true; fi; \
	done; \
	sleep 2; \
	for port in $(DEV_PORTS); do \
		pids=$$(lsof -nP -ti tcp:$$port -sTCP:LISTEN); \
		if [ -n "$$pids" ]; then echo "port $$port: force stopping $$pids"; kill -9 $$pids || true; fi; \
	done

# Fresh local stack: free the dev ports, then run the API and the board together. Ctrl+C stops both.
dev: kill-ports
	$(MAKE) -j2 api app

# Usage: make jh ARGS="doctor"
# .env.tpl holds op:// references. .env holds local values (API key, vault path).
jh:
	cd api && op run --env-file=../.env.tpl --env-file=../.env -- uv run jobhunt $(ARGS)

# Local stack. op run injects secrets from .env.tpl and .env.
up:
	op run --env-file=.env.tpl --env-file=.env -- docker compose up -d --build

# Dump this project's database. Does not overwrite ~/jobhunt-backup.dump.
pg-dump:
	PGPASSWORD=jobhunt $(PG_BIN)/pg_dump -h 127.0.0.1 -p 54330 -U jobhunt -Fc jobhunt \
		> $(HOME)/jobhunt-$$(date +%Y%m%d%H%M).dump

# Resume worker on the host, against the Postgres.app database. Uses the same key injection.
resume-worker:
	cd api && op run --env-file=../.env.tpl --env-file=../.env -- env JOBHUNT_ALLOW_OFFSITE=1 \
		DATABASE_URL='$(APP_DATABASE_URL)' uv run jobhunt resume worker
