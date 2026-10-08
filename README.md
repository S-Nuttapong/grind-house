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

Live network tests are off unless you pass `-m live`.

## Scheduling

The hourly tick is a launchd job (`jobhunt ops install-launchd`). If 1Password is locked, `op run` fails and that hour is skipped. The next hour tries again.
