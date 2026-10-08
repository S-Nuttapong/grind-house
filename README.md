# Job Hunt OS

Personal system that collects software-engineering jobs into Postgres, drops duplicates, ranks each job against a brag bank, and shows the result in a local filter UI.

The governing spec is [PLAN.md](PLAN.md). The database shape is [schema.sql](schema.sql).

## Run

Secrets stay in 1Password. `.env.tpl` holds `op://` references only.

```bash
make jh ARGS="--help"
```

That runs `op run --env-file=.env.tpl -- uv run jobhunt`.

## Tests

Postgres for tests:

```bash
docker compose -f docker-compose.test.yml up -d
```

`TEST_DATABASE_URL` defaults to `postgresql://jobhunt:jobhunt@127.0.0.1:54329/jobhunt_test?sslmode=disable`. That password is only for the local Docker database.

```bash
make check
```

Live network tests are off unless you pass `-m live` and override the default marker filter: `uv run pytest -m live`.

## Local dashboard

The board is a Next.js app in `web/` (Tailwind, shadcn/ui). It reads a FastAPI JSON API; the API contract is `http://127.0.0.1:8765/openapi.json`.

Everything in Docker (Postgres, API, board):

```bash
docker compose up -d --build
```

The board is on `http://127.0.0.1:3000` and the API on `http://127.0.0.1:8765`. Inside the containers the processes listen on `0.0.0.0` so Docker can publish them; the host ports are bound to `127.0.0.1` only.

For local development, start Postgres with `docker compose up -d postgres`, then run these in two terminals:

```bash
make api   # FastAPI JSON API on 127.0.0.1:8765
make web   # Next.js dev server on 127.0.0.1:3000, proxies /api to the API
```

`web/` needs `npm ci` once. Behind the TLS gateway, set `NODE_EXTRA_CA_CERTS="$PWD/.certs/ca-bundle.pem"` for npm and Node. `make check-web` runs typecheck, lint, and a production build.

To fill the board from the public company list, run the scrape on the host against that database:

```bash
DATABASE_URL='postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable' \
VAULT_BANK_PATH=/tmp/jobhunt-bank \
uv run jobhunt scrape --source greenhouse
```

The same local password is only for this Docker database. This network intercepts TLS with a Cloudflare Gateway CA, so Python will not trust the public boards until you point it at a bundle that includes that CA:

```bash
export SSL_CERT_FILE="$PWD/.certs/ca-bundle.pem"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
```

Build that file by appending the gateway certificate (from the macOS system keychain) to certifi’s `cacert.pem`. Do not commit it. Ashby’s public API is still blocked by the gateway, so that source stays empty.

`companies.seed.yaml` is a starter set of public Greenhouse and Lever boards. Replace it with the companies you want.

## Scheduling

The hourly tick is a launchd job (`jobhunt ops install-launchd`). If 1Password is locked, `op run` fails and that hour is skipped. The next hour tries again.
