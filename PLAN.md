# Job Hunt OS — Implementation Plan

Owner: San (Nuttapong Saelek) · Version 1.0 · 2026-10-07
Companion files: `schema.sql` (database, tested on Postgres 16) · design doc "Job Hunt OS Design" (why each decision was made)

---

## 0. How to use this plan (instructions for the coding agent)

1. Build **phase by phase, task by task**, in the order given in §17. Do not start a task until the previous task's acceptance criteria pass.
2. After every task: run `uv run ruff check . && uv run ruff format --check . && uv run mypy jobhunt && uv run pytest -q`. All must pass.
3. Commit once per task: `T1.3: <short summary>`.
4. Follow the guardrails in §2 at all times. If a task seems to need breaking one, stop and ask.
5. Field names for third-party APIs in this plan are a starting point. For every adapter, **save a real response as a fixture first**, then write the mapping from the fixture. The fixture wins over this document.
6. Keep functions small, typed, and pure where possible. Put I/O at the edges (adapters, db, web).
7. Don't add a dependency that isn't in §3 without saying why in the commit message.

---

## 1. Goal and scope

A personal system that collects software-engineering jobs from many sources into one Postgres database, removes duplicates, ranks each job against San's brag bank with an explainable score, and shows them in a local filter UI. Claude drives scoring and daily digests through an MCP server.

**In scope (v1):** source adapters, normalization, dedupe, closure detection, fetch scopes with schedules, rules (saved filters + notify), profile builder from the brag bank, hard filters, prefilter, LLM rubric with evidence check, deterministic scoring, calibration, filter UI, MCP server, hourly tick, retention.

**Out of scope (v1):** auto-applying, cover letters, Gmail status updates, hosted UI, multi-user, logged-in scraping of any site.

**Pipeline**

```
fetch scope due ─► adapter.fetch() ─► normalize ─► dedupe/upsert ─► close missing
                                                          │
                     profile.json (from brag bank) ──┐    ▼
                                                     ├─► hard filters ─► prefilter ─► shortlist
                                                     │                                   │
                                     Claude via MCP ◄┴───────── next_to_score ◄──────────┘
                                          │
                                          └─► save_assessment ─► evidence check ─► score ─► rules ─► digest
```

Note: LLM extraction and the rubric run **only on the shortlist**, in one step per job. Hard filters and the prefilter are deterministic and run on every new job.

---

## 2. Guardrails (non-negotiable)

**Scraping**
- Never scrape any site while logged in. Never ask for, store, or use session cookies (e.g. LinkedIn `li_at`, `JSESSIONID`). No fake accounts.
- No proxies, no CAPTCHA solving, no stealth/anti-bot evasion.
- Respect each source's `min_interval` (§8). One request at a time per host, with 1–3 s random delay between requests to the same host.
- Identify the client with a clear `User-Agent` for official APIs (ATS, HN, RemoteOK, Remotive). Keep JobSpy's defaults for the boards it handles.
- On HTTP 429 or 403: stop that source for the rest of the run, mark the run `partial`, log it. Do not retry in a loop.

**Secrets**
- No secrets in code, tests, fixtures, logs, or commits. `DATABASE_URL` and any later API keys are injected at runtime with 1Password CLI (`op run --env-file=.env.tpl -- …`). `.env.tpl` holds only `op://` references. Any real `.env` is gitignored.
- Never print or log `DATABASE_URL`. Redact connection strings in error messages.
- Use a personal GitHub repo and personal accounts, separate from work tools.

**Brag bank (Obsidian vault)**
- The vault is **read-only** for this app. Never write, move, or delete anything in it.
- The local Postgres may store bank entry text and resume text, so fit scoring can run without reading the vault every time. This is a deliberate exception, recorded because the database is local and single-user ([ADR-0001](docs/adr/0001-single-tenant-postgres-task-pipeline.md)).
- Entries marked `confidential: true` keep that flag. A fit model with `sends_data_offsite = true` never receives those entries or their text.
- Contact details from `_Profile.md` (email, phone) are never imported.
- Tests use a synthetic bank in `tests/fixtures/bank/`, never the real vault.

**Code**
- SQL is parameterized. Column and field names in dynamic SQL come only from the whitelist in §12. Never interpolate user input into SQL.
- The web server binds to `127.0.0.1` only.
- Fixtures contain only public job data.

---

## 3. Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.12 |
| Packaging | `uv` (pyproject + `uv.lock`) |
| DB | Postgres 16 on Neon (prod), `postgres:16` in Docker (tests) |
| DB access | `psycopg[binary]` 3, `psycopg_pool`, plain SQL in `jobhunt/db/queries/*.sql` or module constants |
| Migrations | `dbmate` (brew), files in `db/migrations/`, run with `--no-dump-schema` |
| HTTP | `httpx` (sync client), `tenacity` for backoff on 5xx/timeouts |
| Aggregator scraping | `python-jobspy` (pin exact version) |
| Parsing | `markdownify` (HTML→Markdown), `pycountry`, `python-dateutil` |
| Models / config | `pydantic` v2, `pydantic-settings`, `PyYAML` |
| Scheduling | `croniter`, `cron-descriptor`, `zoneinfo` |
| CLI | `typer` |
| Web API | `fastapi`, `uvicorn` (JSON only, pydantic response models, OpenAPI at `/openapi.json`) |
| Web UI | Next.js 16 (App Router, TypeScript) in `web/`, Tailwind CSS 4, shadcn/ui, `react-markdown`; npm with exact versions |
| MCP | official `mcp` Python SDK (`from mcp.server.fastmcp import FastMCP`), stdio transport |
| Tests | `pytest`, `respx` (httpx mocks), `pytest-cov` |
| Lint / types | `ruff`, `mypy` (strict on `jobhunt/`) |

---

## 4. Repository layout

```
jobhunt/
  pyproject.toml
  uv.lock
  README.md
  PLAN.md                      # this file
  .env.tpl                     # op:// references only
  .gitignore                   # .env, .venv, __pycache__, data/, exports/, *.log
  docker-compose.test.yml      # postgres:16 for tests
  db/
    migrations/
      20261007000001_init.sql          # schema.sql wrapped in dbmate markers
      20261007000002_seed_sources.sql
  config/
    prefs.yaml                 # San's hard-filter preferences
    companies.seed.yaml        # initial target companies
    scopes.seed.yaml           # initial fetch scopes
    synonyms.yaml              # skill terms + synonyms + stack/domain dictionary
    fx.yaml                    # static FX rates to USD, with as_of date
    regions.yaml               # region word → UTC offset band (APAC, EMEA, ...)
  prompts/
    assess_v1.md               # extraction + rubric instructions for Claude
  jobhunt/
    __init__.py
    settings.py                # pydantic-settings: DATABASE_URL, VAULT_BANK_PATH, ...
    cli.py                     # typer app
    log.py                     # structured logging with redaction
    http.py                    # shared httpx client, per-host delay, UA
    models.py                  # RawPosting, NormalizedJob, FetchScope, Filter, Assessment, ...
    db/
      __init__.py              # pool, transaction helper, advisory lock
      repo.py                  # all SQL access
    sources/
      __init__.py              # registry: id → adapter
      base.py                  # SourceAdapter protocol
      greenhouse.py  lever.py  ashby.py
      jobspy_src.py            # indeed, linkedin_guest, glassdoor, ziprecruiter
      hn.py  remoteok.py  remotive.py      # P2
      detect.py                # ATS detection from a careers URL
    normalize/
      company.py  title.py  level.py  location.py  salary.py  text.py
    ingest.py                  # run a scope: fetch → normalize → dedupe → close
    tick.py                    # due scopes, locks, next_run_at
    schedule.py                # cron validation, plain words, next runs, guardrails
    filters.py                 # filter DSL → SQL (whitelist)
    profile.py                 # brag bank → profile (in-memory + sanitized DB copy)
    match/
      hard.py                  # prefs → filter DSL
      prefilter.py             # deterministic keyword score
      evidence.py              # check cited bank ids
      score.py                 # rubric labels → score, band
      assess.py                # save_assessment orchestration
    rules.py                   # evaluate rules, write rule_hits
    retention.py
    calibrate.py
    mcp_server.py
    web/
      app.py                   # FastAPI app factory (JSON API only)
      api.py                   # /api/* routes and pydantic response models
      board.py                 # board queries (filters, list, detail, events, runs)
  web/                         # Next.js UI (talks only to /api, proxied to FastAPI)
    src/app/                   # pages: board, pipeline, runs
    src/components/            # shadcn/ui primitives + job card, detail, filters
    src/lib/api.ts             # typed client matching /openapi.json
  tests/
    conftest.py                # db fixture: migrate once, transaction-per-test rollback
    fixtures/
      greenhouse/*.json  lever/*.json  ashby/*.json  jobspy/*.csv
      bank/                    # synthetic brag bank
    unit/  integration/  e2e/
  ops/
    com.san.jobhunt.tick.plist # launchd template
```

---

## 5. Configuration and secrets

`.env.tpl` (committed, contains no secrets):

```
DATABASE_URL=op://Personal/jobhunt-neon/direct_url
VAULT_BANK_PATH=/Users/Nuttapong_1/vaults/San Personal Space/San Life Engineering - 2026-2027/Brag Banks 2026-2027
JOBHUNT_TZ=Asia/Bangkok
```

- Run everything as `op run --env-file=.env.tpl -- uv run jobhunt <cmd>`. Add a `Makefile` or `just` alias `jh` for this.
- Use Neon's **direct** (non-pooler) connection string. The tick uses a session-level advisory lock, which doesn't work through a transaction-mode pooler.
- `settings.py` loads via `pydantic-settings`; `DATABASE_URL` is a `SecretStr`.

`config/prefs.yaml` (defaults; San edits):

```yaml
levels: [senior, staff, principal, lead, unknown]
locations:
  countries: [SG, TH]            # onsite or hybrid allowed here
  remote:
    allowed: true
    tz_band: [5, 10]             # remote roles must overlap UTC+5..+10, or be unknown
  # us_remote: true              # uncomment to include US-remote roles
posted_within_days: 21
salary_floor_usd_year: 60000     # applied only when salary is listed
employment_types: [fulltime, null]
exclude_companies: []            # name_norm values
exclude_title_terms: [intern, "new grad", "data entry"]
shortlist_per_day: 40
```

`config/fx.yaml`:

```yaml
as_of: 2026-10-01                # update by hand monthly
to_usd:
  USD: 1.0
  # SGD: <rate>   add real rates for SGD, THB, EUR, GBP, AUD, INR; a missing currency → usd_year_min = NULL
```

`config/regions.yaml`: `APAC: [5, 10]`, `SEA: [7, 8]`, `EMEA: [-1, 4]`, `Americas: [-10, -3]`, `US: [-10, -4]`, `Europe: [0, 3]`.

`config/synonyms.yaml`: canonical term → synonyms, plus a `kind` (stack | concept | domain), e.g.

```yaml
react: {kind: stack, syn: [react.js, reactjs]}
typescript: {kind: stack, syn: [ts]}
nextjs: {kind: stack, syn: [next.js, next]}
web performance: {kind: concept, syn: [core web vitals, lighthouse, page speed]}
fintech: {kind: domain, syn: [payments, banking, lending, earned wage access]}
```

---

## 6. Database

- `db/migrations/20261007000001_init.sql` = `schema.sql` with `-- migrate:up` at the top and a `-- migrate:down` section that drops everything in reverse order.
- `20261007000002_seed_sources.sql` inserts:

| id | kind | min_interval | close_after |
|---|---|---|---|
| greenhouse | ats | 6 hours | null |
| lever | ats | 6 hours | null |
| ashby | ats | 6 hours | null |
| indeed | aggregator | 6 hours | 14 days |
| linkedin_guest | aggregator | 12 hours | 14 days |
| glassdoor | aggregator | 24 hours | 14 days |
| ziprecruiter | aggregator | 24 hours | 14 days |
| hn | feed | 24 hours | 45 days |
| remoteok | feed | 12 hours | 21 days |
| remotive | feed | 12 hours | 21 days |

- `20261008000003_job_fit.sql` adds the job fit tables (§13.8), mirrored in `schema.sql`:

| table | holds |
|---|---|
| bank_entries | one row per brag-bank entry (BB-###), body text included |
| bank_profile | single row: the profile body without contact details |
| resumes | uploaded or imported resume text; exactly one `is_selected` |
| fit_sources | sha256 of the profile text a scoring run used |
| job_fits | score per (job, model, source), with matched and missing terms |
| fit_schedules | cron and timezone per mode; the only place cron is stored |
| fit_runs | queued / running / ok / failed, with an idempotency key |
| fit_run_events | append-only progress log, replayed by the SSE stream |
| fit_worker | single row: model id and heartbeat |

- `jobhunt seed` loads `companies.seed.yaml` and `scopes.seed.yaml` idempotently (upsert by `name_norm` / scope `name`).
- `jobhunt/db/__init__.py` provides: `pool()`, `tx()` context manager, `advisory_lock(name) -> bool` using `pg_try_advisory_lock(hashtext(name))` on a dedicated connection held for the lock's lifetime.
- All SQL lives in `db/repo.py` (or `.sql` files it loads). No SQL elsewhere.

---

## 7. Source adapters

### 7.1 Interface (`sources/base.py`)

```python
class RawPosting(BaseModel):
    source_id: str
    source_job_id: str              # stable id from the source; else sha256(source_url)
    source_url: str
    apply_url: str | None
    company_name: str
    company_hint: dict = {}         # e.g. {"ats": "greenhouse", "slug": "acme"} or {"company_url": ...}
    title: str
    location_raw: str | None
    remote_hint: str | None         # raw value like "Remote", "hybrid", workplaceType
    description_html: str | None
    description_text: str | None
    posted_at: date | None
    employment_type_raw: str | None
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_currency: str | None
    salary_interval_raw: str | None
    level_hint: str | None          # LinkedIn job_level etc.
    payload: dict                   # the raw item, stored in raw_payloads on change

class SourceAdapter(Protocol):
    id: str
    kind: Literal["ats", "aggregator", "feed"]
    full_board: bool                # True when a fetch returns the company's entire board
    def fetch(self, scope: FetchScope, ctx: FetchContext) -> Iterator[FetchBatch]: ...
```

`FetchBatch` = `(company_key | None, list[RawPosting])`. For `full_board` adapters, one batch per company, so `ingest` can close missing jobs per company.

### 7.2 Greenhouse (`greenhouse.py`)
- `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- Expected item fields: `id`, `title`, `absolute_url`, `location.name`, `updated_at`, `content` (HTML, **HTML-escaped** → `html.unescape` before markdownify), `departments`, `offices`; use `first_published` if present, else `updated_at`, for `posted_at`.
- `source_job_id = str(id)`; `apply_url = absolute_url`.
- Scope params: `{"tiers": ["A","B"]}` or `{"company_ids": [...]}`. One request per company.
- 404 → mark company `ats = null` in a review list (log), continue.

### 7.3 Lever (`lever.py`)
- `GET https://api.lever.co/v0/postings/{slug}?mode=json`
- Expected fields: `id`, `text` (title), `hostedUrl`, `applyUrl`, `categories.location`, `categories.commitment`, `workplaceType`, `createdAt` (epoch ms), `descriptionPlain`/`description`, `lists`, `additionalPlain`, `salaryRange` if present.
- Description = description + lists (as Markdown bullets) + additional.

### 7.4 Ashby (`ashby.py`)
- `GET https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true`
- Expected fields under `jobs[]`: `id`, `title`, `location`, `isRemote`/`workplaceType`, `publishedAt`, `jobUrl`, `applyUrl`, `descriptionHtml`/`descriptionPlain`, `employmentType`, compensation summary. Confirm from the fixture.

### 7.5 JobSpy (`jobspy_src.py`)
- One adapter class parameterized by site: `indeed`, `linkedin_guest` (JobSpy site `linkedin`), `glassdoor`, `ziprecruiter`.
- Call `jobspy.scrape_jobs(site_name=[site], search_term, location, is_remote, hours_old, job_type, results_wanted, country_indeed, description_format="markdown", fetch_description=<bool>, verbose=0)`.
- Never pass `proxies`. Caps: `results_wanted ≤ 100` for `linkedin_guest`, `≤ 200` otherwise. `fetch_description=True` only for LinkedIn and only when `results_wanted ≤ 50`.
- Map DataFrame columns (confirm against a saved CSV fixture): `id` (if present, else sha256 of `job_url`), `job_url`, `job_url_direct` (→ `apply_url`), `title`, `company`, `company_url`, `location`, `is_remote`, `date_posted`, `job_type`, `interval`, `min_amount`, `max_amount`, `currency`, `description`, `job_level`.
- Wrap the call: catch exceptions and 429-like errors → `RunPartial`.
- Record `company_url` in `company_hint` so discovered companies can be ATS-detected later.

### 7.6 Feeds (P2)
- `hn.py`: find the latest "Ask HN: Who is hiring?" story via `https://hn.algolia.com/api/v1/search?tags=story,author_whoishiring&query=who%20is%20hiring`, then `https://hn.algolia.com/api/v1/items/{id}` and treat each top-level comment as a posting. First line usually holds `Company | Role | Location | Remote | Salary`; parse it best-effort, keep full text as description.
- `remoteok.py`: `GET https://remoteok.com/api` (first array element is a notice; skip it). Show a "via Remote OK" link in the UI as their terms ask.
- `remotive.py`: `GET https://remotive.com/api/remote-jobs?category=software-dev`. Check their docs for call limits and respect them.

### 7.7 ATS detection (`detect.py`)
- Input: a company's careers or homepage URL. Fetch once (timeout 10 s).
- Regex the HTML for `boards.greenhouse.io/{slug}`, `job-boards.greenhouse.io/{slug}`, `boards-api.greenhouse.io/v1/boards/{slug}`, `jobs.lever.co/{slug}`, `jobs.ashbyhq.com/{slug}`.
- Verify by calling the matching API; accept only on HTTP 200 with a jobs list.
- Writes `companies.ats`, `ats_slug`. Never guesses.

---

## 8. Normalization (`normalize/`)

All functions are pure and unit-tested with table-driven tests.

- **company.py** `norm_company(name) -> str`: lowercase, strip accents, remove punctuation, collapse spaces, strip trailing legal suffixes (`inc, llc, ltd, limited, pte, pte ltd, co, corp, corporation, gmbh, plc, sdn bhd, bv, sa, ag, (thailand), (singapore)`). Resolve via `company_aliases` before creating a company. Unknown companies from aggregators are created with `tier = NULL` (review queue).
- **title.py** `norm_title(title) -> str`: lowercase; expand `sr→senior, jr→junior, swe→software engineer, eng→engineer, dev→developer`; unify `front-end/front end→frontend`, `back-end→backend`, `full-stack/full stack→fullstack`; drop parenthetical or trailing segments that are just a location or "remote"; remove punctuation; collapse spaces. Keep seniority words.
- **level.py** `infer_level(title, level_hint) -> Level`: first match wins: intern → `intern`; `junior|graduate|entry` → `junior`; `principal` → `principal`; `staff` → `staff`; `head of|director|manager` → `manager`; `tech lead|lead` → `lead`; `senior` → `senior`; LinkedIn `job_level` mapping; else `unknown`.
- **location.py** `parse_location(raw, remote_hint) -> (country, city, remote, tz_min, tz_max)`: `pycountry` + alias map (US state codes → US, "Bangkok" → TH, "Singapore" → SG, "UK" → GB); remote words (`remote, work from home, wfh, anywhere`) → `remote`; `hybrid` → `hybrid`; explicit `UTC±N`/`GMT±N` → tz band; region words via `regions.yaml`. Unknown stays `unknown`/NULL; never guess a country.
- **salary.py** `normalize_salary(min, max, currency, interval) -> (..., usd_year_min)`: map interval words; annualize (hourly × 2080, daily × 260, weekly × 52, monthly × 12); convert with `fx.yaml`; if currency missing or not in table → `usd_year_min = NULL`.
- **text.py**: `html_to_md` (markdownify, strip scripts/styles, collapse blank lines), `content_hash(title_norm, description_md)` = sha256 hex.

`dedupe_key = f"{company_id}|{title_norm}|{country or '??'}"`.

---

## 9. Ingest, dedupe, closing (`ingest.py`)

`run_scope(scope_id) -> RunResult`, all inside one transaction per batch:

1. Insert `runs` row (`status='running'`, `scraper_version` = package version).
2. For each `FetchBatch`, for each `RawPosting`:
   1. Normalize → `NormalizedJob`.
   2. Resolve or create company.
   3. **Existing posting?** `SELECT … FROM postings WHERE source_id=$1 AND source_job_id=$2`.
      - Yes: update `last_seen_at`, `last_run_id`; if `content_hash` changed, update the job's fields and description, insert `raw_payloads`; bump `jobs.last_seen_at`; reopen the job if it was closed (`closed_at = NULL`). Count `updated`.
   4. **New posting:** find a candidate job:
      ```sql
      SELECT id, similarity(title_norm, $title) AS s
      FROM jobs
      WHERE company_id = $company AND closed_at IS NULL
        AND (dedupe_key = $key
             OR (coalesce(country,'??') = coalesce($country,'??')
                 AND title_norm % $title AND similarity(title_norm, $title) >= 0.85
                 AND last_seen_at > now() - interval '14 days'))
      ORDER BY (dedupe_key = $key) DESC, s DESC
      LIMIT 1;
      ```
      - Threshold 0.85 was checked on Postgres: plurals and reordered words merge (0.89–1.0); "senior" vs "staff" (0.63), frontend vs backend (0.58) and an added team suffix (0.74) stay separate. Keep it in settings so it can be tuned.
      - Found: attach posting to that job. If the new posting is from an ATS and the job's `apply_url` is from an aggregator, replace `apply_url`. Fill NULL job fields (salary, posted_at, remote) from the new posting.
      - Not found: insert job, then posting. Count `new_jobs`.
      - Insert `raw_payloads` for the new posting.
3. **Close missing (full_board adapters only),** per company batch:
   ```sql
   UPDATE jobs j SET closed_at = now()
   WHERE j.company_id = $company AND j.closed_at IS NULL
     AND EXISTS (SELECT 1 FROM postings p WHERE p.job_id = j.id AND p.source_id = $source)
     AND NOT EXISTS (
       SELECT 1 FROM postings p
       WHERE p.job_id = j.id
         AND (p.last_run_id = $run
              OR (p.source_id <> $source AND p.last_seen_at > now() - interval '14 days')))
   RETURNING j.id;
   ```
   Skip closing for a company whose fetch failed (never close on error).
4. **Aggregator close (daily, in tick):** jobs with no posting seen within its source's `close_after` → `closed_at = now()`.
5. Finish `runs` row: counts, `finished_at`, `status` (`ok` | `partial` | `failed`), `error` (redacted).

**Acceptance tests (integration):** same fixture twice → 0 new jobs on run 2; Greenhouse + LinkedIn posting of the same job → 1 job, 2 postings, `apply_url` = Greenhouse; posting removed from fixture on run 2 → job closed; fetch error for one company → none of its jobs closed; JD edited → `raw_payloads` row added, job description updated.

---

## 10. Fetch scopes, schedule, tick

### 10.1 `schedule.py`
- `validate(cron, tz, source) -> list[str]` errors: invalid cron; invalid IANA tz; minimum gap between consecutive runs (check the next 20 runs with croniter) is less than `sources.min_interval`.
- `describe(cron) -> str` via cron-descriptor ("At 07:00, Monday through Friday").
- `next_runs(cron, tz, n=3) -> list[datetime]` in the scope's tz.
- Scope param schemas per source (pydantic models), used by the UI to render only valid fields:
  - ATS: `tiers: list[A|B|C]`, `company_ids: list[int] | None`
  - JobSpy: `search_term`, `location`, `country_indeed`, `is_remote`, `hours_old (1..168)`, `job_type`, `results_wanted`
  - Feeds: `query` (optional)

### 10.2 `tick.py` — `jobhunt tick`
1. Acquire `advisory_lock("jobhunt.tick")`. If not acquired, exit 0 ("another tick is running").
2. `SELECT … FROM fetch_scopes WHERE enabled AND (next_run_at IS NULL OR next_run_at <= now()) ORDER BY next_run_at NULLS FIRST`.
3. For each due scope: `run_scope`, then set `last_run_at = now()`, `next_run_at = croniter.next` (in scope tz, stored UTC). A failing scope doesn't stop the others.
4. Daily (first tick after 03:00 local): aggregator close (§9.4) and retention (§15).
5. After fetching: `match.run_deterministic()` on new/changed jobs (hard filters + prefilter, §13), then `rules.evaluate()` (§12.3).
6. Release lock. Print a one-line summary per scope.

### 10.3 launchd (`ops/com.san.jobhunt.tick.plist`)
- `StartInterval` 3600, `RunAtLoad` false, `StandardOutPath`/`StandardErrorPath` to `~/Library/Logs/jobhunt/tick.log`.
- `ProgramArguments`: `/bin/zsh -lc "cd ~/code/jobhunt && op run --env-file=.env.tpl -- uv run jobhunt tick"`.
- If 1Password is locked, `op run` fails; the tick is skipped and the next hour retries. Document this in README.
- `jobhunt ops install-launchd` writes the plist to `~/Library/LaunchAgents/` and runs `launchctl bootstrap gui/$UID …`; `ops uninstall-launchd` reverses it.

Hourly is deliberate: each tick wakes the Neon compute (scale-to-zero after 5 min), and hourly keeps usage well inside the free 100 CU-hours/month.

---

## 11. Profile from the brag bank (`profile.py`)

- Reads `VAULT_BANK_PATH`: `_Profile.md` (frontmatter + body) and `Entries/*.md` (frontmatter: `id, title, company, role, period, my_role, scope, metrics, strength, confidential, status, tags, sources`).
- Builds two objects:
  - **`BankView` (in memory only, never stored):** `{id: {title, terms, period, my_role, strength, confidential}}`. `terms` = canonical terms from `synonyms.yaml` found in the entry's tags, title, and body.
  - **`ProfileSanitized` (stored in `profiles`):** `{level, years, titles: [...], skills: {term: [bank ids]}, domains: {term: [ids]}, prefs: <prefs.yaml>}`. No titles of entries, no metrics, no body text. Confidential entries contribute ids and terms only.
- `hash = sha256(canonical JSON of ProfileSanitized)`. Insert if new.
- `jobhunt profile build` prints the hash, number of entries, and top 30 terms with counts.
- If the brag-bank kit's `bankutil.py` is available at `<bank>/_kit/bankutil.py`, it may be imported read-only for frontmatter parsing; otherwise implement a small YAML frontmatter parser.

---

## 12. Filter DSL (`filters.py`)

One JSON model used by the board, rules, and hard filters.

```json
{"all": [
  {"field": "level", "op": "in", "value": ["senior", "staff"]},
  {"any": [
    {"field": "country", "op": "in", "value": ["SG", "TH"]},
    {"all": [{"field": "remote", "op": "eq", "value": "remote"},
             {"field": "tz", "op": "overlaps", "value": [5, 10]}]}
  ]},
  {"field": "text", "op": "matches", "value": "react OR \"web platform\""},
  {"field": "salary_usd_year_min", "op": "gte_or_null", "value": 60000},
  {"field": "posted_at", "op": "within_days", "value": 21}
]}
```

### 12.1 Whitelist

| field | SQL | ops |
|---|---|---|
| level, remote, country, employment_type | `j.<col>` | eq, in, not_in, is_null |
| city | `j.city` | eq, in, contains |
| company | `c.name_norm` | in, not_in |
| company_tier | `c.tier` | in, is_null |
| source | `EXISTS (SELECT 1 FROM postings p WHERE p.job_id=j.id AND p.source_id = ANY(%s))` | in |
| text | `j.search @@ websearch_to_tsquery('english', %s)` | matches |
| title | `j.title_norm` | contains, not_contains |
| salary_usd_year_min | `j.salary_usd_year_min` | gte, gte_or_null |
| posted_at | `j.posted_at` | within_days, within_days_or_null |
| first_seen_at | `j.first_seen_at` | within_days |
| tz | `j.tz_min, j.tz_max` | overlaps (NULLs pass) |
| score | `m.score` | gte, lte |
| band | `m.band` | in |
| status | `s.status` | in, is_null |
| open | `j.closed_at IS NULL` | eq true |

- `compile(filter) -> (sql_where: str, params: list)`. Unknown field/op → `ValueError`. Max depth 4, max 30 conditions.
- `board_query(filter, sort, limit, offset)` joins `jobs j`, `companies c`, and LEFT JOINs `prefilter pf`, `matches m` (current profile hash and prompt version), `job_status s`.
- Tests: every op; nested any/all; injection attempts in values and field names; NULL handling for `tz` and `gte_or_null`.

### 12.2 URL encoding
The board keeps the filter as query params (`?level=senior&level=staff&country=SG&q=react&min_score=60`). `filters.from_query(params)` builds the DSL; `filters.to_query(dsl)` does the reverse for the simple flat case. "Save as rule" sends the DSL.

### 12.3 Rules (`rules.py`)
- `evaluate(job_ids | None)`: for each enabled rule, run its compiled filter restricted to the given job ids (or all open jobs on first enable); upsert `rule_hits (rule_id, job_id)`.
- `digest(since) -> list`: hits with `notified_at IS NULL` and (`notify_min_score IS NULL` or score ≥ it), joined with job + match; `mark_notified(ids)`.

---

## 13. Matching

### 13.1 Hard filters (`match/hard.py`)
`prefs.yaml` → filter DSL (§12). Applied to new/changed open jobs and to all open jobs when the profile hash changes. Writes `prefilter (job_id, profile_hash, passed_hard, filter_reason)`; `filter_reason` = first failing condition (e.g. `level:junior`, `location:US-onsite`, `title_term:intern`).

### 13.2 Prefilter (`match/prefilter.py`)
Deterministic, no LLM:

```
terms_in_title = canonical terms found in title
terms_in_jd    = canonical terms found in description
profile_terms  = keys of profile.skills ∪ profile.domains

score = 3.0 * |terms_in_title ∩ profile_terms|
      + 1.0 * |terms_in_jd ∩ profile_terms|
      + 1.5 * |domain terms in jd ∩ profile.domains|
      + 2.0 if level ∈ {senior, staff}
      - 0.5 * |stack terms in jd − profile_terms|   (capped at -5)
```
Store it in `prefilter.score` for jobs that passed hard filters. Once per tick, mark up to `shortlist_per_day` of today's unassessed passing jobs as `shortlisted = true` (highest score first, then most recent `posted_at`), counting jobs already shortlisted today against the cap. A job is "waiting for assessment" when `shortlisted` and it has no `matches` row for the current profile hash and prompt version. `matches` rows exist only for assessed jobs.

### 13.3 Assessment via Claude (`match/assess.py`, `prompts/assess_v1.md`)
`next_to_score(limit)` returns for each shortlisted job: `job_id, title, company, location, salary, posted_at, description_md (≤ 12k chars), prompt_version`, plus once per call the **BankView summary** `[{id, title, terms}]` read live from the vault (not stored) and `prompts/assess_v1.md`.

Claude returns an `Assessment`:

```json
{
  "job_id": 123,
  "prompt_version": "assess_v1",
  "model": "claude-…",
  "requirements": {
    "level": "senior",
    "must": [{"text": "...", "jd_quote": "..."}],
    "nice": [{"text": "...", "jd_quote": "..."}],
    "stack": ["react", "typescript"],
    "domain": ["fintech"],
    "logistics": {"country": "SG", "remote": "hybrid", "tz": null,
                  "visa_sponsorship": "unknown", "salary": null}
  },
  "criteria": [
    {"criterion": "must_have", "requirement": "...", "jd_quote": "...",
     "label": "met", "evidence": ["BB-012"], "note": "..."},
    {"criterion": "level", "requirement": "Senior IC owning a platform", "label": "met", "evidence": ["BB-003"]},
    {"criterion": "stack", "requirement": "GraphQL", "label": "gap", "evidence": []},
    {"criterion": "domain", "requirement": "payments", "label": "adjacent", "evidence": ["BB-020"]},
    {"criterion": "logistics", "requirement": "Hybrid in Singapore", "label": "unknown", "evidence": []}
  ]
}
```

`prompts/assess_v1.md` must instruct Claude to:
- Extract at most 5 must-haves from the JD's required/minimum qualifications, each with a verbatim `jd_quote`.
- Label each criterion `met | adjacent | gap | unknown`.
- Cite only bank ids from the provided list; `met`/`adjacent` require at least one id whose terms support the requirement.
- Never infer skills that no bank entry shows. When unsure, use `gap` (skills) or `unknown` (logistics).
- Return JSON only, matching the schema.

### 13.4 Evidence check (`match/evidence.py`)
For each `met`/`adjacent` line: every cited id must exist in BankView, and the requirement's canonical terms (via `synonyms.yaml`) must intersect the union of the cited entries' terms. If the requirement has no recognizable term, accept when ids exist but set `note += " (unverified term)"`. On failure: label → `gap`, `evidence_ok = false`, `note += " evidence rejected: <reason>"`. Otherwise `evidence_ok = true`.

### 13.5 Score (`match/score.py`)

```python
WEIGHTS = {"must_have": 40, "level": 20, "stack": 15, "domain": 10, "logistics": 15}
VAL = {"met": 1.0, "adjacent": 0.5, "gap": 0.0, "unknown": 0.0}

def criterion_value(kind, lines):
    if not lines:
        return 0.5                                  # no info → neutral
    if kind == "logistics":
        if any(l.label == "gap" for l in lines): return 0.0
        if all(l.label == "met" for l in lines): return 1.0
        return 0.5                                  # some unknown
    return sum(VAL[l.label] for l in lines) / len(lines)

def score(lines, posted_at, today):
    by = group_by_criterion(lines)
    s = sum(w * criterion_value(k, by.get(k, [])) for k, w in WEIGHTS.items())
    must_gaps = sum(1 for l in by.get("must_have", []) if l.label == "gap")
    if must_gaps >= 2: s = min(s, 49)
    if posted_at and (today - posted_at).days > 30: s -= 10
    s = max(0, min(100, round(s)))
    band = "apply" if s >= 80 else "maybe" if s >= 60 else "skip"
    return s, band
```
Table-driven unit tests: all met → 100; two must gaps → ≤ 49; stale → −10; logistics conflict → logistics 0; empty criterion → neutral.

### 13.6 `save_assessment` transaction
Validate (pydantic) → evidence check → score → upsert `requirements (job_id, prompt_version)` → upsert `matches` on `(job_id, profile_hash, prompt_version)` (on conflict: delete its old `match_criteria`, update score/band/model) → insert `match_criteria` rows → `rules.evaluate([job_id])`. Return `{score, band, rejected: [...]}`.

### 13.7 Calibration (`calibrate.py`, `/calibrate`)
- `jobhunt calibrate sample --n 40`: stratified sample of scored jobs (≈ 1/3 per band), shown in `/calibrate` for San to label `apply | maybe | skip` → `labels (origin='calibration')`.
- UI skip/save/apply actions also write `labels (origin='ui_action')` (skip → skip, save → maybe, applied → apply).
- `jobhunt calibrate report`: band agreement %, precision@10 (of the top 10 scored, share labeled apply), confusion matrix, per `prompt_version`. Shown on `/calibrate`.
- Changing `prompt_version` or weights: re-score the calibration set; the report compares versions.

### 13.8 Job fit (`fit/`)

Pre-computed fit scores for every open job, against two sources: the whole brag bank, and the selected resume. Scores are stored in `job_fits` and only ever computed by the fit worker or the CLI, never inside a request ([ADR-0001](docs/adr/0001-single-tenant-postgres-task-pipeline.md)).

**Model interface** (`fit/base.py`). Every strategy (BGE now, Claude or Cursor later) implements:

```python
class JobFitModel(ABC):
    model_id: str                 # stored with every score, e.g. "bge-base-en-v1.5/v1"
    sends_data_offsite: bool = False

    def score(self, job_description: str, profile_text: str) -> float: ...   # 0..100
    def score_many(self, profile_text: str, job_descriptions: Sequence[str]) -> list[float]: ...
```

`fit/registry.py` maps `FIT_MODEL` (default `bge`) to a factory. Adding a strategy is one class plus one registry line.

**BGE strategy** (`fit/bge.py`). `BgeFitModel` loads `BAAI/bge-base-en-v1.5` once per worker process. Job descriptions are prefixed with `Represent this sentence for searching relevant passages: `. Raw cosine similarity is calibrated with `max(0, min(100, (raw - 0.40) / 0.45 * 100))`. Because the model truncates at 512 tokens and the bank is far longer, the profile is split into one chunk per bank entry (or resume section) and each job description into ~400-token chunks; the raw score is the mean, over the job's chunks, of each chunk's best match among the profile chunks. That is one matrix `cos_sim` per batch, not a Python loop over pairs.

**Tiers:** strong ≥ 80, good ≥ 60, fair ≥ 40, low below 40.

**Sources** (`fit/sources.py`). Bank text = profile body plus, per entry, title, scope, metrics, body, and tags. A model with `sends_data_offsite = true` gets the non-confidential entries only. The sha256 of the text is upserted into `fit_sources`. Editing the bank or selecting a resume creates a new hash; it does not score anything. The board keeps showing the last source whose `scored_at` is set.

**Keywords** (`fit/keywords.py`). Canonical terms from `synonyms.yaml` present in both texts are `matched_terms`; terms in the job description but not the profile are `missing_terms`. Both are stored on `job_fits` during the run.

**Runner** (`fit/runner.py`). `run_fit(conn, model, mode, limit=None)` selects open jobs whose `job_hash` (sha256 of title + description) is missing or different in `job_fits` for this model and source, scores them in batches of 64, and upserts. Unchanged jobs are skipped, so a rerun is cheap and a bank edit (new hash) rescores everything.

**Schedule** (`fit/schedule.py`). `validate(cron, tz)` rejects bad cron, unknown timezones, and a gap under 15 minutes between runs. `describe(cron)` and `next_runs(cron, tz, n)` back the schedules page. This is the shared helper §10.1 describes.

**Worker** (`jobhunt fit worker`, its own process and container). Loads the model once. Every 60 seconds, in order: due `fit_schedules`, queued manual runs, then new or changed jobs from the latest scrape (both modes). It claims a run with `FOR UPDATE SKIP LOCKED`, holds `advisory_lock("jobhunt.fit")`, and writes a `fit_run_events` progress row plus `pg_notify('fit_run_<id>', event_id)` after each batch, in the same transaction as that batch's scores. On SIGTERM it finishes the current batch, marks the run `queued`, and exits, so a restart resumes with only the unscored jobs left. It heartbeats `fit_worker` each poll. An idempotency key (sha256 of schedule, mode, source hash, and the cron slot or the current minute) makes a repeated trigger return the existing run.

**CLI.** `jobhunt profile import` reads the vault read-only into `bank_entries`, `bank_profile`, and `resumes`. `jobhunt fit run --mode bank|resume`, `jobhunt fit download-model` (caches into `./.models`, because the TLS gateway blocks the download inside containers), and `jobhunt fit score --job ID` (prints match %, tier, matched and missing terms for one job).

---

## 14. Web UI (Next.js + FastAPI JSON API)

`jobhunt serve` → `uvicorn jobhunt.web.app:create_app --factory --host 127.0.0.1 --port 8765` serves JSON only.
The UI is a Next.js app in `web/` (`npm --prefix web run dev`, bound to `127.0.0.1:3000`). Next.js rewrites `/api/*` to `JOBHUNT_API_URL` (default `http://127.0.0.1:8765`), so the browser talks to one origin and FastAPI needs no CORS. FastAPI's OpenAPI document is the contract for `web/src/lib/api.ts`.

| API route | Purpose | UI page |
|---|---|---|
| `GET /api/jobs?q&where&remote&source&posted_within&has_salary&include_closed&fit&min_score&sort&page` | `{jobs, total, page, pages, page_size}`; `fit` is `bank` (default) or `resume`; `sort=match` is the default | Board list |
| `GET /api/jobs/{id}` | Job with `description_md`, `postings`, `events`, `tailor_prompt` | Board detail pane, mobile sheet |
| `POST /api/jobs/{id}/events` | JSON `{status, reason?}`; status ∈ saved, skipped, applied; returns the job | Save / skip (with reason) / applied |
| `GET /api/facets` | Source ids and remote types for filter controls | Board filters |
| `GET /api/pipeline` | Jobs with a status, grouped saved / applied / skipped | Pipeline kanban |
| `GET /api/runs` | Recent runs with counts and errors | Runs |
| `GET/POST/PUT/DELETE /api/profile/entries`, `GET/PUT /api/profile/summary` | Brag bank entries and the profile body | Profile |
| `GET/POST /api/resumes`, `POST /api/resumes/{id}/select`, `DELETE /api/resumes/{id}` | Resume text; upload is multipart, 5 MB, pdf/md/txt/json | Profile |
| `GET/POST/PUT/DELETE /api/fit/schedules` | Cron schedules; invalid cron, timezone, or a gap under 15 min returns 422 | Schedules |
| `POST /api/fit/schedules/{id}/run` | Queues a run and returns 202; the worker picks it up | Schedules |
| `GET /api/fit/runs`, `GET /api/fit/runs/{id}` | Run list, and one run with its latest progress | Schedules |
| `GET /api/fit/runs/{id}/stream` | SSE: replay `fit_run_events`, then tail `LISTEN/NOTIFY`; `Last-Event-ID` resumes | Schedules |
| `GET /api/fit/status` | Model id, scored counts per mode, stale flag, worker heartbeat | Board, Schedules |
| Later: `/api/rules*`, `/api/scopes*`, `/api/companies`, `/api/calibrate` | Same purposes as before (builders, previews, run now, review, labels) | Rules, Scopes, Companies, Calibrate |

Every job carries `score` (0–100) and `fit_tier` (strong / good / fair / low) from `job_fits` for the active model and the latest source of the requested mode whose `scored_at` is set, so the board keeps showing the previous scores while a new run is in progress. Both are `null` until the first fit run, and the card then shows "Not scored yet". `matched_terms` and `missing_terms` come from the same row. Money in API responses is a string so it stays exact. Job description Markdown is rendered in the browser with raw HTML skipped.

**Board card:** title, company, location + remote pill, salary (original currency), age ("3d"), source pills, score badge ("86% Strong", colored by tier). Unscored jobs show "Not scored yet". The detail pane shows the score, its source (brag bank or resume), and the matched and missing terms.

**Detail:** full JD (Markdown rendered, must-have `jd_quote`s highlighted), criteria table (label, JD quote, bank ids, evidence_ok), all source URLs, apply link, status history, "Copy tailor prompt".

**Filters panel:** Match group (score against: brag bank or selected resume; minimum score: any, 40+, 60+, 80+), source, remote type, posted within, salary listed, include closed, text search, location, sort (best match by default, date posted, recently found).

**Profile page** (`/profile`): brag bank entries (search, create, edit, delete, every schema field) and the profile summary; resumes (upload, select exactly one, preview the extracted text, delete).

**Schedules page** (`/schedules`): the `fit_schedules` table with plain-English cron, the next three runs, an enabled switch, and Run now; a create/edit dialog with presets (hourly, daily 07:00, weekdays) and inline validation; recent fit runs with a live progress bar driven by `useFitRun` (EventSource to the SSE route, TanStack Query polling every 2s as fallback, state persisted to localStorage so a reopened tab shows the last progress immediately). The board header shows a "Scoring N%" pill while a run is active.

Styling: Tailwind + shadcn/ui, Inter, light and dark themes (system default plus a toggle). Board layout: left filter sidebar, job list with a match score ring per card, sticky detail pane; one column with a detail sheet on mobile. ⌘K opens a command palette for job search and navigation. Every form control has a `<label>`. Keyboard focus visible.

---

## 15. Retention (`retention.py`, daily in tick)

```sql
DELETE FROM raw_payloads WHERE fetched_at < now() - interval '14 days';

UPDATE jobs j SET description_md = NULL
WHERE j.closed_at < now() - interval '90 days'
  AND j.description_md IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM job_events e WHERE e.job_id = j.id)
  AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.job_id = j.id);

DELETE FROM requirements r USING jobs j
WHERE r.job_id = j.id AND j.description_md IS NULL;

DELETE FROM runs WHERE started_at < now() - interval '180 days';
```
Then record `pg_database_size(current_database())` for `/runs`. Warn in tick output and on `/runs` at ≥ 70% of 1 GB.

---

## 16. MCP server (`mcp_server.py`)

`jobhunt mcp` starts a FastMCP stdio server named `jobhunt`.

| Tool | Args | Returns |
|---|---|---|
| `search_jobs` | `filter` (DSL) or simple args, `limit≤50` | compact rows: id, title, company, location, score, band, status, url |
| `get_job` | `job_id` | full job, postings, requirements, criteria, status history |
| `next_to_score` | `limit≤10` | shortlisted jobs + bank summary + assess prompt (§13.3) |
| `save_assessment` | `Assessment` | `{score, band, rejected}` |
| `run_scope` | `scope_id` | run summary (respects lock + guardrail) |
| `list_scopes` / `save_scope` | scope (saved **paused**) | |
| `list_rules` / `save_rule` | rule (saved **paused**) | |
| `set_status` | `job_id, status, note?` | event row (origin `claude`) |
| `digest` | `since?` | unnotified rule hits with score ≥ threshold; marks them notified |
| `stats` | — | counts per source/stage/band, DB size, last runs |

Claude Desktop / Cowork config snippet for README (no secrets inline):

```json
{"mcpServers": {"jobhunt": {
  "command": "/bin/zsh",
  "args": ["-lc", "cd ~/code/jobhunt && op run --env-file=.env.tpl -- uv run jobhunt mcp"]
}}}
```

**Morning digest prompt** (README, for a Cowork scheduled task, weekdays 08:00):
> Use the jobhunt tools. Call `next_to_score` and assess each job per the returned prompt, then `save_assessment`, until nothing is left or 40 jobs are done. Then call `digest` and give me the top 10 new matches: score, band, company, role, location, one line on the strongest match and the biggest gap, and the job id.

**Tailor handoff:** in Cowork, "Tailor my resume for jobhunt job #123" → Claude calls `get_job` and passes the JD to the `tailor-resume` skill. The app never writes into the vault.

---

## 17. Phases and tasks

### P0 — Foundations and core data (week 1)

- **T0.1 Scaffold.** `uv init`, layout §4, ruff/mypy/pytest config, `.gitignore`, `.env.tpl`, `docker-compose.test.yml`, README skeleton, `Makefile` with `jh` wrapper.
  *Accept:* `uv run pytest` runs (0 tests ok); `uv run jobhunt --help` lists commands.
- **T0.2 Settings + logging.** `settings.py` (`SecretStr`), `log.py` with redaction of URLs containing credentials.
  *Accept:* unit test proves a `postgres://user:pass@host/db` string is redacted in logs and exceptions.
- **T0.3 Migrations.** Wrap `schema.sql` as `…001_init.sql` (+ down), add `…002_seed_sources.sql`. `jobhunt db migrate` shells out to dbmate with `--no-dump-schema`.
  *Accept:* migrate up/down/up clean on Docker Postgres; tests' `conftest.py` migrates once per session and rolls back per test.
- **T0.4 DB layer.** Pool, `tx()`, `advisory_lock`, `repo.py` functions for companies, scopes, runs, jobs, postings, raw_payloads.
  *Accept:* integration tests for each repo function; two concurrent `advisory_lock` calls → only one gets it.
- **T0.5 Normalizers.** All of §8 with table-driven tests (≥ 10 cases each for title, level, location, salary).
  *Accept:* tests pass; mypy strict clean.
- **T0.6 HTTP client.** Shared `httpx.Client`, UA, timeouts, per-host delay, tenacity on 5xx/timeouts only, 429/403 → `SourceBlocked`.
  *Accept:* respx tests for retry, no-retry on 429, delay honoured (mock clock).
- **T0.7 ATS adapters.** Record one real fixture each (Greenhouse, Lever, Ashby) from public boards; implement mappings from fixtures.
  *Accept:* fixture tests map ≥ 95% of items with title, company, url, location_raw populated.
- **T0.8 Ingest + dedupe + close.** §9 in full.
  *Accept:* all §9 acceptance tests pass.
- **T0.9 Seeds + CLI.** `jobhunt seed`, `jobhunt scrape --scope <id> | --source <id>`, `jobhunt doctor` (DB reachable, migrations current, vault path readable, sizes).
  *Accept:* against Neon: 30 companies seeded, `scrape` on ATS scope loads ≥ 500 jobs, second run adds 0 new jobs, `doctor` all green.

### P1 — Reach and scheduling (week 2)

- **T1.1 ATS detection** (§7.7) + `/companies` review data in repo (UI later).
  *Accept:* respx tests for each ATS pattern; never writes without a verified 200.
- **T1.2 JobSpy adapter** for `indeed` then `linkedin_guest` (§7.5) with saved CSV fixtures.
  *Accept:* fixture mapping tests; live smoke test (marked `@pytest.mark.live`, skipped by default) fetching ≤ 20 Indeed SG results.
- **T1.3 Schedule module** (§10.1).
  *Accept:* tests: invalid cron, invalid tz, LinkedIn every 6 h rejected, weekdays 07:00 accepted, plain-words text, next 3 runs in Asia/Bangkok.
- **T1.4 Tick** (§10.2) + `jobhunt tick` + aggregator close.
  *Accept:* e2e with fake adapter: two due scopes run, `next_run_at` advances, a failing scope doesn't block the other, concurrent tick exits 0.
- **T1.5 launchd** (§10.3) install/uninstall commands + README section.
  *Accept:* plist renders with correct paths; `install-launchd --dry-run` prints it.
- **T1.6 Run health.** `jobhunt stats`; runs summary query.
  *Accept:* daily run on real scopes completes < 10 min with no 429 for a week (manual check, note in README).

### P2 — Matching (week 3)

- **T2.1 Profile builder** (§11) with synthetic bank fixture.
  *Accept:* sanitized profile contains no entry titles/metrics/body (test asserts); confidential entries give ids+terms only; hash stable across runs.
- **T2.2 Filter DSL** (§12) incl. whitelist and injection tests.
  *Accept:* all §12.1 ops tested; malicious field/value rejected or safely parameterized.
- **T2.3 Hard filters + prefilter** (§13.1, §13.2).
  *Accept:* `jobhunt match` writes `prefilter` rows (reasons for failures, scores for passes) and shortlists ≤ 40 per day.
- **T2.4 Assessment schema, evidence check, score** (§13.3–13.6) + `prompts/assess_v1.md`.
  *Accept:* §13.5 tests; evidence rejection test (cited id lacks the term → gap, `evidence_ok=false`); DB CHECK still holds.
- **T2.5 MCP server** tools `next_to_score`, `save_assessment`, `get_job`, `search_jobs`, `stats`.
  *Accept:* in-process MCP tests call each tool; manual: Claude assesses 5 jobs end to end.
- **T2.6 Calibration** CLI (§13.7).
  *Accept:* report prints agreement and precision@10. Target before P3 sign-off: precision@10 ≥ 0.7 on San's 40 labels.
- **T2.7 Job fit schema + model** (§13.8). Tables, `JobFitModel`, BGE strategy, fake strategy, registry, keyword matching.
  *Accept:* calibration clamps to 0–100; a second `run_fit` scores nothing; editing the bank changes the source hash and the next run rescores.
- **T2.8 Fit worker** (§13.8). Claim with `SKIP LOCKED`, idempotency key, per-batch progress plus `pg_notify`, resume after a crash, SIGTERM, heartbeat.
  *Accept:* two workers claiming at once take different runs; a killed run resumes and scores only the remaining jobs; the SSE stream replays history, resumes from `Last-Event-ID` with no duplicates, and ends on the final status event.
- **T2.9 Profile + schedules API** (§14). Entry and resume CRUD, schedule validation (422 on bad cron, timezone, or a gap under 15 min), queue run returns 202, fit status with the stale flag.
  *Accept:* integration tests cover each route; the board's `sort=match` and `min_score` read stored scores only.
- **T2.10 Profile + schedules UI.** `/profile`, `/schedules` with live progress, the match filter group, the score badge, and the scoring pill.
  *Accept:* Playwright covers the board sorted by score, a schedule edit, and a run whose progress survives a reload.

### P3 — UI and orchestration (week 4)

- **T3.1 Web skeleton** (app factory, base template, static, 127.0.0.1 bind).
- **T3.2 Board + detail + events** (§14).
  *Accept:* filter changes update results without full reload; URL reflects filters; save/skip writes `job_events` and `labels`.
- **T3.3 Rules builder + preview + evaluate** (§12.3, §14).
  *Accept:* "Save as rule" from a board view reproduces the same result count in preview.
- **T3.4 Scopes builder + schedule preview + run now.**
  *Accept:* guardrail error shown inline; run now respects lock.
- **T3.5 Runs, companies review, calibrate pages.**
- **T3.6 MCP remaining tools** (`run_scope`, scopes/rules tools saved paused, `set_status`, `digest`) + README for Cowork config, digest prompt, tailor handoff.
  *Accept:* digest returns only unnotified hits above threshold and marks them.
- **T3.7 Retention** (§15) in tick + size warning.
  *Accept:* integration test with backdated rows.

### Later (not v1)
HN / RemoteOK / Remotive adapters (P2-ready interfaces exist), Glassdoor/ZipRecruiter, cover letters from the bank, Gmail status updates as `job_events (origin='gmail')`, embeddings with pgvector for the prefilter, hosted UI behind login.

---

## 18. Testing strategy

- **Unit:** normalizers, schedule, filters compiler, prefilter, evidence, score. Pure, fast, table-driven.
- **Adapter:** respx/CSV fixtures only; live tests opt-in with `-m live`.
- **Integration:** Docker Postgres from `docker-compose.test.yml`, `TEST_DATABASE_URL` (no secrets; local only). Migrate once per session; each test in a rolled-back transaction.
- **E2E:** fake adapter → `tick` → match → `save_assessment` with a canned Assessment → rule hit → digest.
- Coverage target 85% on `jobhunt/` excluding `web/templates`.

---

## 19. Decisions still open (defaults in place)

| Decision | Default used | Where to change |
|---|---|---|
| Target locations, remote tz band | SG + TH onsite/hybrid; remote overlapping UTC+5..+10 | `config/prefs.yaml` |
| First 30 companies | none; San fills `companies.seed.yaml` (name + careers URL; detector finds ATS) | `config/companies.seed.yaml` |
| Initial fetch scopes | ATS tiers A+B daily 07:00; Indeed SG + TH `software engineer` 48 h daily 07:30; LinkedIn guest SG `frontend engineer` 48 h at 08:00 and 20:00 | `config/scopes.seed.yaml` or UI |
| Write shortlisted jobs to Obsidian | no (vault stays read-only) | revisit after v1 |

`companies.seed.yaml` format:

```yaml
- name: <Company>
  careers_url: https://<company>/careers
  tier: A            # A dream, B good, C backup
  # ats / ats_slug filled by `jobhunt companies detect`
```
