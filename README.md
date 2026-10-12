# Job Hunt OS

Personal system that collects software-engineering jobs into Postgres, drops duplicates, ranks each job against a brag bank, and shows the result in a local filter UI.

The governing spec is [PLAN.md](PLAN.md). The database shape is [api/db/schema.sql](api/db/schema.sql).

## Layout

- `api/`: Python project (FastAPI JSON API, Typer CLI, scrape, fit, and resume workers). Code is grouped into feature slices under `api/jobhunt/`: `core`, `scrape`, `jobs`, `brag`, `profile`, `fit`, `resume`.
- `app/`: Next.js board. Code is grouped into feature slices under `app/src/features/`: `shell`, `jobs`, `scrape`, `brag`, `profile`, `fit`, `resume`.
- Root: `docker-compose.yml`, this README, `PLAN.md`, `docs/adr/`, `Makefile`.

## Run

Secrets stay in 1Password. `.env.tpl` holds `op://` references only.

```bash
make jh ARGS="--help"
```

That runs `op run --env-file=.env.tpl -- uv run jobhunt` from `api/`.

## Tests

Postgres for tests:

```bash
docker compose -f api/docker-compose.test.yml up -d
```

`TEST_DATABASE_URL` defaults to `postgresql://jobhunt:jobhunt@127.0.0.1:54329/jobhunt_test?sslmode=disable`. That password is only for the local Docker database.

```bash
make check
```

Live network tests are off unless you pass `-m live` and override the default marker filter: `uv run pytest -m live` (from `api/`).

## Local dashboard

The board is a Next.js app in `app/` (Tailwind, shadcn/ui). It reads the FastAPI JSON API; the API contract is `http://127.0.0.1:8765/openapi.json`.

Everything in Docker (Postgres, API, board):

```bash
docker compose up -d --build
```

The board is on `http://127.0.0.1:3000` and the API on `http://127.0.0.1:8765`. Inside the containers the processes listen on `0.0.0.0` so Docker can publish them; the host ports are bound to `127.0.0.1` only.

For local development, start Postgres with `docker compose up -d postgres`, then run these in two terminals:

```bash
make api   # FastAPI JSON API on 127.0.0.1:8765
make app   # Next.js dev server on 127.0.0.1:3000, proxies /api to the API
```

`app/` needs `npm ci` once. Behind the TLS gateway, set `NODE_EXTRA_CA_CERTS="$PWD/../.certs/ca-bundle.pem"` for npm and Node when running from `app/`. `make check-app` runs typecheck, lint, and a production build.

To fill the board from the public company list, run the scrape on the host against that database (from `api/`):

```bash
DATABASE_URL='postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable' \
VAULT_BANK_PATH=/tmp/jobhunt-bank \
uv run jobhunt scrape --source greenhouse
```

The same local password is only for this Docker database. This network intercepts TLS with a Cloudflare Gateway CA, so Python will not trust the public boards until you point it at a bundle that includes that CA:

```bash
export SSL_CERT_FILE="$PWD/../.certs/ca-bundle.pem"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
```

Build that file by appending the gateway certificate (from the macOS system keychain) to certifi’s `cacert.pem`. Do not commit it. Ashby’s public API is still blocked by the gateway, so that source stays empty.

`api/config/companies.seed.yaml` is a starter set of public Greenhouse and Lever boards. Replace it with the companies you want.

## Job fit

Scores are written to Postgres by a worker. Opening the board does not score anything.

Import the brag docs. Contact details in the profile frontmatter are not stored. `jobhunt brag-docs migrate-vault` (add `--write` to rewrite) converts old vault entries once, after copying `Entries/` out of the vault. Run these from `api/`.

```bash
VAULT_BANK_PATH="/path/to/Brag Banks" uv run jobhunt profile import
```

Download the embedding model on the host. A container on this network cannot reach the download, so the worker reads a cache you build here. The cache goes to `./.models` at the repo root, which is gitignored:

```bash
cd api
uv sync --extra fit
HF_HOME=../.models uv run jobhunt fit download-model
```

```bash
docker compose up -d --build fit-worker
```

The worker uses the same Dockerfile as the API (`api/Dockerfile`) with the `fit` extra, which installs CPU torch. The API image leaves that extra off. `HF_HOME=/models` and `./.models` is mounted read-only. On stop, Docker waits 60 seconds so the worker can finish its current batch; the next start scores only the jobs still missing.

Schedules are rows in the database. Change them on the Schedules page at `http://127.0.0.1:3000/schedules`. The worker re-reads that table every minute, so a change does not need a restart.

The default scorer is `MatrixFitScorer("qwen3")`, a local embedding model. Swap it in [composition.py](api/jobhunt/composition.py), as below. Do not log something you would not put on a resume.

## Resume generation

A **Generate resume** button on a scored job queues a run. The `resume-worker` claims it, runs the Claude Agent SDK on Haiku 5.5, and stores the PDF. See [ADR-0005](docs/adr/0005-resume-agent.md).

Copy the vault kit into the gitignored directory the worker reads. `ANTHROPIC_API_KEY` lives in gitignored `.env`, not in `.env.tpl`.

```bash
make jh ARGS="resume sync-kit"
make up
```

`make up` is `op run --env-file=.env.tpl -- docker compose up -d --build`. To run the worker on the host against the compose database:

```bash
make resume-worker
```

On Apple Silicon, if `python` is the x86_64 build, the SDK's bundled CLI hangs. Point `RESUME_CLI` at a native `claude` binary from Claude Code 2.1.296 or newer, so it recognizes `claude-haiku-5-5`. An older CLI mis-prices that model and can stop the run.

Token cost is on `http://127.0.0.1:3000/admin/usage`, linked from the command menu only.

The Playwright check drives the board. A free run sets `writer=FakeResumeWriter()` in `composition.py`. Artifacts, including the PDF, stay in gitignored `app/e2e/artifacts/`.

```bash
cd app && npm run uat
```

## Swap an adapter

`api/jobhunt/composition.py` is the only file that picks adapters. Implement the port, then change its line:

```python
COMPOSITION = Composition(
    sources=[GreenhouseSource(), ...],
    parser=DefaultParser(),          # or ClaudeParser()
    scorer=MatrixFitScorer("qwen3"), # or ClaudeFitScorer()
    writer=ClaudeSdkWriter(),        # or FakeResumeWriter()
    store=PgStore(),
)
```

Ports are `JobSource`, `DetailParser`, `FitScorer`, `ResumeWriter`, and `Store`. An adapter that sends text off this machine refuses to run unless `JOBHUNT_ALLOW_OFFSITE=1`. See [ADR-0006](docs/adr/0006-composition-root.md) and [ADR-0007](docs/adr/0007-claude-adapters.md).

## Scheduling

Searches live at http://127.0.0.1:3000/searches. `jobhunt tick` polls markets that are due (LinkedIn and SEEK about every 30 minutes, Indeed and Glassdoor twice a day, API boards daily) and runs Greenhouse, Lever, and Ashby scopes. launchd starts that every 15 minutes:

```bash
cd api && uv run jobhunt ops install-launchd
```

`--dry-run` prints the plist. `ops uninstall-launchd` removes it. Logs go to `~/Library/Logs/jobhunt/tick.log`.

Each tick turns Cloudflare WARP off, scrapes, then turns it back on if it was connected (`api/config/scrape.yaml`, `scripts/vpn.sh`). If 1Password is locked, `op run` fails and that tick is skipped. The next one tries again. A corporate TLS intercept skips scraping and still restores the VPN.
