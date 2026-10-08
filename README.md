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

Postgres and the web UI:

```bash
docker compose up -d --build
```

The site is published on `http://127.0.0.1:8765`. Inside the container the process listens on `0.0.0.0` so Docker can publish it; the host port is bound to `127.0.0.1` only.

To fill the board from the public company list, run the scrape on the host against that database:

```bash
DATABASE_URL='postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable' \
VAULT_BANK_PATH=/tmp/jobhunt-bank \
uv run jobhunt scrape --source greenhouse
```

The same local password is only for this Docker database. Ashby’s public API is blocked by the network gateway on this machine, so that source stays empty until the gateway allows it.

`companies.seed.yaml` is a starter set of public Greenhouse and Lever boards. Replace it with the companies you want.

## Scheduling

The hourly tick is a launchd job (`jobhunt ops install-launchd`). If 1Password is locked, `op run` fails and that hour is skipped. The next hour tries again.
