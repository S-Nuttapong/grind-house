# Job Hunt OS — Implementation Plan

Owner: San (Nuttapong Saelek) · Version 1.0 · 2026-10-07
Companion files: `api/db/schema.sql` (database, tested on Postgres 16) · design doc "Job Hunt OS Design" (why each decision was made)

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

A personal system that collects software-engineering jobs from many sources into one Postgres database, removes duplicates, ranks each job against San's brag bank with an explainable score, and shows them in a local filter UI.

**In scope (v1):** source adapters, normalization, dedupe, closure detection, fetch scopes with schedules, profile and brag docs, job fit scoring (`fit_tier`), filter UI, resume generation, hourly tick, retention.

**Out of scope (v1):** auto-applying, cover letters, Gmail status updates, hosted UI, multi-user, logged-in scraping of any site. The unused rubric path (hard filters, prefilter, saved rules) is dropped ([ADR-0011](docs/adr/0011-fit-replaces-rubric.md)).

**Pipeline**

```
fetch scope due ─► adapter.fetch() ─► normalize ─► dedupe/upsert ─► close missing
                                                          │
                     brag docs + selected resume ─────────┴─► fit worker ─► job_fits ─► board
```

Fit scores are computed by the fit worker, never inside a request. The board reads the stored `fit_tier`.

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

**Brag docs (Obsidian vault)**
- The vault is **read-only** for this app, with one exception: `jobhunt brag-docs migrate-vault --write` rewrites `Entries/*.md` frontmatter to the BragDoc shape once. It copies `Entries/` to `~/.jobhunt/vault-backups/<timestamp>/` first, leaves each file's body byte-for-byte, and skips files already in the new shape. After that, `jobhunt profile import` only reads ([ADR-0002](docs/adr/0002-brag-docs.md)).
- The local Postgres may store brag doc text and resume text, so fit scoring can run without reading the vault every time. This is a deliberate exception, recorded because the database is local and single-user ([ADR-0001](docs/adr/0001-single-tenant-postgres-task-pipeline.md)).
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
| Migrations | `dbmate` (brew), files in `api/db/migrations/`, run with `--no-dump-schema` |
| HTTP | `httpx` (sync client), `tenacity` for backoff on 5xx/timeouts |
| Aggregator scraping | `python-jobspy` (pin exact version) |
| Parsing | `markdownify` (HTML→Markdown), `pycountry`, `python-dateutil` |
| Models / config | `pydantic` v2, `pydantic-settings`, `PyYAML` |
| Scheduling | `croniter`, `cron-descriptor`, `zoneinfo` |
| CLI | `typer` |
| Web API | `fastapi`, `uvicorn` (JSON only, pydantic response models, OpenAPI at `/openapi.json`) |
| Web UI | Next.js 16 (App Router, TypeScript) in `app/`, Tailwind CSS 4, shadcn/ui, `react-markdown`; npm with exact versions |
| MCP | official `mcp` Python SDK (`from mcp.server.fastmcp import FastMCP`), stdio transport |
| Tests | `pytest`, `respx` (httpx mocks), `pytest-cov` |
| Lint / types | `ruff`, `mypy` (strict on `jobhunt/` and `api/`) |

---

## 4. Repository layout

```
plan/
  README.md  PLAN.md  docs/adr/   # spec, decisions, runbook
  docker-compose.yml             # postgres, api, fit-worker, ui
  Makefile                       # check, check-app, api, app, jh
  .env.tpl                       # op:// references only
  api/                           # Python project (uv, FastAPI, Typer)
    pyproject.toml  uv.lock  Dockerfile  docker-compose.test.yml
    db/migrations/               # dbmate; db/schema.sql is the reference shape
    config/                      # prefs, companies/scopes seeds, synonyms, fx, regions
    jobhunt/
      core/                      # settings, db pool, migrate, cli root, http, log, paths
      composition.py             # the only file that picks adapters
      scrape/                    # sources/, normalize/, ingest, runner, repo, router, seed, cli
      facts/                     # parser, contract checks, merge, backfill
      jobs/                      # board queries and /api/jobs routes
      brag/                      # brag docs, tags, metric keys, vault migration
      profile/                   # profile summary, resumes, bank import
      fit/                       # scoring models, worker, schedules, repo, router, cli
    tests/                       # mirrors jobhunt/ (core, scrape, jobs, brag, profile, fit)
  app/                           # Next.js project (App Router, Tailwind, shadcn/ui)
    Dockerfile  package.json  next.config.ts  components.json  AGENTS.md
    src/
      app/                       # thin routes: pages, layout, error
      components/                # shared shadcn/ui primitives and small widgets
      features/                  # shell, jobs, scrape, brag, profile, fit
        <feature>/api.ts         # server-only fetchers for /api/*
        <feature>/types.ts       # types mirroring the API models
        <feature>/actions.ts     # server actions
        <feature>/components/    # feature UI
      lib/                       # api-client (request helper), utils, hooks
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

- `api/db/migrations/20261007000001_init.sql` = `schema.sql` with `-- migrate:up` at the top and a `-- migrate:down` section that drops everything in reverse order.
- `20261007000002_seed_sources.sql` inserts:

| id | kind | min_interval | close_after |
|---|---|---|---|
| greenhouse | ats | 6 hours | null |
| lever | ats | 6 hours | null |
| ashby | ats | 6 hours | null |
| indeed | aggregator | 6 hours (15 minutes after `20261011000009`) | 14 days |
| seek | aggregator | 15 minutes | 14 days |
| linkedin_guest | aggregator | 12 hours (15 minutes after `20261011000009`) | 14 days |
| glassdoor | aggregator | 24 hours (15 minutes after `20261011000009`) | 14 days |
| ziprecruiter | aggregator | 24 hours | 14 days |
| naukri | aggregator | 24 hours | 14 days |
| adzuna | aggregator | 24 hours | 14 days |
| reed | aggregator | 24 hours | 14 days |
| jooble | aggregator | 24 hours | 14 days |
| mycareersfuture | feed | 12 hours | 21 days |
| hn | feed | 24 hours | 45 days |
| remoteok | feed | 12 hours | 21 days |
| remotive | feed | 12 hours | 21 days |

- `20261008000003_job_fit.sql` adds the job fit tables (§13.8). `20261009000004_brag_docs.sql` replaces `bank_entries` with the brag doc tables below, copying existing rows. Both are mirrored in `api/db/schema.sql`:

| table | holds |
|---|---|
| tags | user-defined tag names with a hex color; unique on lower(name) |
| metric_keys | reusable metric categories; unique on lower(name) |
| brag_docs | one row per brag doc (BB-###); `quarter` is generated from `date` |
| brag_doc_tags | brag doc to tag |
| brag_doc_metrics | a metric value on a brag doc, pointing at a metric key |
| brag_doc_attachments | http(s) links attached to a brag doc |
| bank_profile | single row: the profile body without contact details |
| resumes | uploaded or imported resume text; exactly one `is_selected` |
| fit_sources | sha256 of the profile text a scoring run used |
| job_fits | score per (job, model, source), with matched and missing terms |
| fit_schedules | cron and timezone per mode; the only place cron is stored |
| fit_runs | queued / running / ok / failed, with an idempotency key |
| fit_run_events | append-only progress log, replayed by the SSE stream |
| fit_worker | single row: model id and heartbeat |

- `jobhunt seed` loads `companies.seed.yaml` and `scopes.seed.yaml` idempotently (upsert by `name_norm` / scope `name`).
- `api/jobhunt/core/db.py` provides: `pool()`, `tx()` context manager, `advisory_lock(name) -> bool` using `pg_try_advisory_lock(hashtext(name))` on a dedicated connection held for the lock's lifetime.
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

class JobSource(Protocol):
    id: str
    spec: SourceSpec                # kind, min_interval, close_after; upserted into sources
    full_board: bool                # True when a fetch returns the company's entire board
    needs_detail_fetch: bool
    def fetch(self, scope: ScopeView, ctx: FetchContext) -> Iterator[FetchBatch]: ...
    def payload_facts(self, payload: dict) -> JobDetail: ...
    def augment_text(self, payload: dict, text: str) -> str: ...
```

The live list is `COMPOSITION.sources` in `jobhunt/composition.py` ([ADR-0006](docs/adr/0006-composition-root.md)). There is no source registry. `ScrapePipeline` upserts `kind`, `min_interval`, and `close_after` and does not change `enabled`. `payload_facts` maps the stored payload. `augment_text` adds lines the description omitted. LinkedIn and SEEK set `needs_detail_fetch`.

`FetchBatch` carries the postings for one company, or for a search page. For `full_board` sources, one batch per company, so `ingest` can close missing jobs per company.

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
- One adapter class parameterized by site: `indeed`, `glassdoor`, `ziprecruiter`, `naukri` (India, cap 50). LinkedIn is not a JobSpy site; see §7.5c.
- Call `jobspy.scrape_jobs(...)`. Indeed and Glassdoor scopes must set `country_indeed` to JobSpy's country name (`Thailand`, `UK`, `Germany`, …). Do not fall back to JobSpy's `usa` default. Naukri omits `country_indeed` unless the scope set it.
- Never pass `proxies`. Caps: `results_wanted ≤ 50` for `naukri`, `≤ 200` otherwise.
- Map DataFrame columns (confirm against a saved CSV fixture): `id` (if present, else sha256 of `job_url`), `job_url`, `job_url_direct` (→ `apply_url`), `title`, `company`, `company_url`, `location`, `is_remote`, `date_posted`, `job_type`, `interval`, `min_amount`, `max_amount`, `currency`, `description`, `job_level`.
- Wrap the call: catch exceptions and 429-like errors → `RunPartial`.
- Record `company_url` in `company_hint` so discovered companies can be ATS-detected later.

### 7.5c LinkedIn guest and SEEK (`linkedin.py`, `seek.py`)
- LinkedIn guest search uses `geoId` and `f_TPR`, parsed with BeautifulSoup. Descriptions come from the detail queue, not the search card. An authwall or captcha page is a partial run, not zero jobs.
- SEEK, JobsDB, and JobStreet share the v5 search on `classification=6281` plus a GraphQL detail call. Indonesia job URLs use `/id/job/{id}`. New Zealand is `nz.seek.com`. Their robots.txt disallows `/api/jobsearch/`; this is accepted for low-volume personal use.
- Scheduled searches in `searches` / `search_sources` / `search_markets` drive these boards. `jobhunt tick` polls markets whose `last_polled_at` is older than that source's `poll_minutes`. ATS company boards stay on `fetch_scopes`.

### 7.5a API boards

Keys stay in the environment (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`, `JOOBLE_API_KEYS`). A missing key finishes the scope as `RunPartial` and does not call the network. Error text must not include the key or the request URL.

| source | call | coverage used here |
|---|---|---|
| adzuna | `GET https://api.adzuna.com/v1/api/jobs/{country}/search/1` | gb, de, nl, fr, au, nz, sg, in. No TH, TW, JP, HK, MY, VN, ID. One page, max 50. Predicted salaries are dropped. Amounts are annual in the feed currency. |
| reed | `GET https://www.reed.co.uk/api/1.0/search` with the key as HTTP basic username and an empty password | UK only. Search salaries are annual. Max 50. |
| jooble | `POST https://{host}/api/{key}` | One key per host (`uk.jooble.org` for GB, `{cc}.jooble.org` otherwise). Free plan is 500 requests per key, lifetime, so one page of 20. No `vn.jooble.org`. |
| mycareersfuture | `POST https://api.mycareersfuture.gov.sg/v2/search` | Singapore. No key. Hidden employer names are skipped. Salary is SGD. |

### 7.5b Boards checked and not added

robots.txt or the lack of a documented API ruled these out. Do not add an HTML scraper for them.

| board | reason |
|---|---|
| StepStone | `Disallow` on the result list and job search |
| Dice | `Disallow` on `/jobsearch/` and `/jobs?q*` |
| 104.com.tw | robots.txt forbids automated scraping of listings |
| Green Japan | `Disallow: /search?` |
| Trade Me Jobs | `Disallow` on search query parameters |
| Wellfound, Wantedly, Cake, JobThai | no documented JSON API; a scraper would depend on page HTML |

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

**Parser** (`facts/`). A new or changed posting becomes a `PostingInput` (structured fields, the augmented description, and `payload_facts`). `COMPOSITION.parser` returns a `JobDetail`. `facts/contract.py` drops a field that fails a rule and logs the rule id. `merge_facts` fills empty job columns only; `level = 'unknown'` counts as empty. The default parser is `DefaultParser`. `ClaudeParser` is the offsite adapter ([ADR-0007](docs/adr/0007-claude-adapters.md)). `jobhunt facts backfill` runs that parser over jobs missing role, location, or level, then pay. It refuses unless `composition.py` sets `ClaudeParser` and `JOBHUNT_ALLOW_OFFSITE=1`.

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
2. If `~/.jobhunt/vpn.state` exists, run `after` hooks first so a crashed tick cannot leave WARP off.
3. Run `before_start` hooks (`api/config/scrape.yaml`). `on_fail: skip_tick` skips scraping. `after` hooks still run.
4. If the TLS certificate for `www.linkedin.com` is not publicly trusted, record `skipped` and do not scrape.
5. Poll due search markets (one thread per source, at most four at a time) and due ATS `fetch_scopes`. A failing source doesn't stop the others. Advance `next_run_at` for each ATS scope.
6. First tick after 03:00 Asia/Bangkok: aggregator close (§9.4). The 7-day catch-up uses the same pass.
7. Release lock. `after` hooks run in `finally`, including VPN restore.

`jobhunt serve` runs this pass at startup and every 15 minutes, and runs the fit worker every minute. The schedules already stored (search poll intervals, ATS cron, fit cron) are what those loops honor.

Searches are edited on `/searches`. Off-topic titles are dropped at ingest and counted in `runs.skipped`. Apply links to Greenhouse, Lever, or Ashby set `companies.ats` and append the company to a discovered ATS scope.

### 10.3 launchd (`ops/com.san.jobhunt.tick.plist`)
- `StartInterval` 900, `RunAtLoad` false, `StandardOutPath`/`StandardErrorPath` to `~/Library/Logs/jobhunt/tick.log`.
- `ProgramArguments`: `/bin/zsh -lc "cd <repo>/api && op run --env-file=../.env.tpl -- uv run jobhunt tick"`.
- If 1Password is locked, `op run` fails; the tick is skipped and the next interval retries.
- `jobhunt ops install-launchd` writes the plist to `~/Library/LaunchAgents/` and runs `launchctl bootstrap gui/$UID …`; `ops uninstall-launchd` reverses it. `--dry-run` prints the plist.

---

## 11. Profile from the brag docs (`profile.py`)

- Reads `VAULT_BANK_PATH`: `_Profile.md` (frontmatter + body) and `Entries/*.md`. Brag doc frontmatter is `id, title, date, company, role, tags, metrics: [{key, value}], attachments: [{type, link}]`. The body is the description.
- `date` is `YYYY-MM-DD`. The database derives `quarter` (`2026-10-08` is `Q4 2026`), so the user never types it.
- Tags and metric keys are shared collections. Importing a name that already exists (case-insensitive) reuses the existing row.
- Builds two objects:
  - **`BankView` (in memory only, never stored):** `{id: {title, terms, date, role}}`. `terms` = canonical terms from `synonyms.yaml` found in the doc's tags, title, and description.
  - **`ProfileSanitized` (stored in `profiles`):** `{level, years, titles: [...], skills: {term: [brag doc ids]}, domains: {term: [ids]}, prefs: <prefs.yaml>}`. No titles of docs, no metrics, no description text.
- `hash = sha256(canonical JSON of ProfileSanitized)`. Insert if new.
- `jobhunt profile build` prints the hash, number of brag docs, and top 30 terms with counts.
- If the brag-bank kit's `bankutil.py` is available at `<bank>/_kit/bankutil.py`, it may be imported read-only for frontmatter parsing; otherwise implement a small YAML frontmatter parser.
- `jobhunt brag-docs migrate-vault` converts the old frontmatter (`period, my_role, scope, strength, confidential, status`, and metrics shaped `{kind, text}`) once. See [ADR-0002](docs/adr/0002-brag-docs.md).

---

## 12. Scoring

The filter DSL, hard filters, keyword prefilter, LLM rubric, and saved rules in the old §12–§13.7 were never built. Those tables are dropped. Scoring is job fit (§13.8) and `fit_tier` (strong, good, fair, low). See [ADR-0011](docs/adr/0011-fit-replaces-rubric.md).

## 13. Matching

### 13.8 Job fit (`fit/`)

Pre-computed fit scores for every open job, against two sources: the whole brag bank, and the selected resume. Scores are stored in `job_fits` and only ever computed by the fit worker or the CLI, never inside a request ([ADR-0001](docs/adr/0001-single-tenant-postgres-task-pipeline.md)).

**Model interface** (`fit/base.py`). Every strategy (the matrix starter now, an LLM or another encoder later) implements one contract ([ADR-0004](docs/adr/0004-pluggable-fit-interface.md)):

```python
class FitScorer(ABC):
    model_id: str                 # stored with every score, e.g. "qwen3-embedding-0.6b/v1"
    sends_data_offsite: bool = False

    def fit(self, docs: Sequence[BragDoc], job_description: str) -> FitResult: ...
    def fit_many(self, docs: Sequence[BragDoc], job_descriptions: Sequence[str]) -> list[FitResult]: ...
```

`BragDoc` is an id and a text. `FitResult` is a 0–100 `score`, the uncalibrated `raw` aggregate, `coverage`, `top_docs` (doc id, the aspect it covers, similarity 0–1), and `gaps`. The scorer is `COMPOSITION.scorer` in `jobhunt/composition.py`. The live scorer is `ClaudeFitScorer` (`claude-haiku-5-5/v3`). `MatrixFitScorer("qwen3")` stays available for comparison. Adding a strategy is one class plus one line there. A scorer with `sends_data_offsite = True` refuses to run unless `JOBHUNT_ALLOW_OFFSITE=1`. `fit/contract.py` drops a match whose doc id was not in the input.

**Claude score** (`fit/claude.py`). v3 asks Haiku for matches only. Link-only bullets and benefits or equal-opportunity bullets are removed first, and fewer than 3 requirements scores 0 with no call. A match that names a `kind: stack` term the doc does not mention is dropped (`fit/keywords.py` `stack_terms_in`), and each doc keeps its strongest matches. Credit `g` is 0 at similarity 0.5 and 1 at 0.9. Coverage is `sum(g) / (N + 2)`. Quality is `sum(g²) / sum(g)`. The score is `100 * 2 * quality * coverage / (quality + coverage)`. One matched requirement scores at most 33. A score of 80 needs evidence on at least two-thirds of `N + 2` requirements. Gaps are the requirements with zero credit. `raw` is unchanged, so resume filler and the resume gate still read it. v1 and v2 keep the model's own score. An empty description is still scored from the title; that is a separate follow-up.

**Matrix starter** (`fit/matrix.py`, `fit/aspects.py`, `fit/select.py`). `qwen3` loads `Qwen/Qwen3-Embedding-0.6B` once per worker process. Each brag doc is one vector. `split_aspects` keeps Markdown bullets and sentences and drops sections whose heading matches benefits, perks, about us, EEO, or salary. Aspects are encoded with the instruction "Given a job requirement, retrieve resume achievements that demonstrate it." The cosine matrix has one row per doc and one column per aspect. Greedy coverage picks up to 10 docs: each step adds the doc with the largest gain in the sum over aspects of the best similarity so far, and stops when that gain drops below 0.01. The raw score is the mean, over the selected rows, of each row's maximum. `bge` is the same matrix model with `BAAI/bge-base-en-v1.5` and the prefix `Represent this sentence for searching relevant passages: `. Each model has its own calibration floor and span, because the cosine ranges differ. The defaults stretch 0.40–0.85 to 0–100: `max(0, min(100, (raw - floor) / span * 100))`. `jobhunt fit calibrate` prints a replacement floor and span from the stored raw scores and does not edit the constants. `fake` implements the same interface with term overlap, for tests.

**Tiers:** strong ≥ 80, good ≥ 60, fair ≥ 40, low below 40.

**Sources** (`fit/sources.py`). Bank mode is one `BragDoc` per brag doc (title, role at company, "Key: value" metric lines, tag names, description) plus the profile summary as id `profile`. Resume mode is one doc per Markdown section, id `resume:<id>#n`. The sha256 covers the ids and texts and is upserted into `fit_sources`. Editing a brag doc or selecting a resume creates a new hash; it does not score anything. The board keeps showing the latest computed row whose source has `scored_at` set. The fit mode stays `bank`.

**Keywords** (`fit/keywords.py`). Canonical terms from `synonyms.yaml` present in both texts are `matched_terms`; terms in the job description but not the joined doc text are `missing_terms`. Both are stored on `job_fits` during the run. `stack_terms_in` returns only `kind: stack` terms. Adding a stack term also adds it to matched and missing terms for every scorer, because they read the same file.

**Runner** (`fit/runner.py`). `run_fit(conn, model, mode, limit=None)` selects open jobs whose `job_hash` (sha256 of title + description) is missing or different in `job_fits` for this model and source, calls `fit_many` in batches of 64, and upserts `job_fits` plus `job_fit_matches`. Unchanged jobs are skipped, so a rerun is cheap and a bank edit (new hash) rescores everything.

**Schedule** (`fit/schedule.py`). `validate(cron, tz)` rejects bad cron, unknown timezones, and a gap under 15 minutes between runs. `describe(cron)` and `next_runs(cron, tz, n)` back the schedules page. This is the shared helper §10.1 describes.

**Worker** (`jobhunt fit worker`, its own process and container). Loads the model once. Every 60 seconds, in order: due `fit_schedules`, queued manual runs, then a scrape-triggered run for each mode when open jobs are unscored or changed for the current source and no scrape run for that mode is already queued. It claims a run with `FOR UPDATE SKIP LOCKED`, holds `advisory_lock("jobhunt.fit")`, and writes a `fit_run_events` progress row plus `pg_notify('fit_run_<id>', event_id)` after each batch, in the same transaction as that batch's scores. On SIGTERM it finishes the current batch, marks the run `queued`, and exits, so a restart resumes with only the unscored jobs left. It heartbeats `fit_worker` each poll. An idempotency key (sha256 of schedule, mode, source hash, and the cron slot or the current minute) makes a repeated trigger return the existing run.

**CLI.** `jobhunt profile import` reads the vault read-only into `brag_docs`, `bank_profile`, and `resumes`. `jobhunt brag-docs migrate-vault` (add `--write` to rewrite) converts old vault entries once. `jobhunt fit run --mode bank|resume`, `jobhunt fit download-model` (caches the selected model into `./.models`, because the TLS gateway blocks the download inside containers), `jobhunt fit score --job ID` (prints match %, tier, the selected docs, gaps, and matched and missing terms), `jobhunt fit calibrate` (prints a floor and span from stored raw scores), and `jobhunt fit eval --labels <file>` (Spearman and hit@10 against a private label file).

---

## 14. Web UI (Next.js + FastAPI JSON API)

`jobhunt serve` → `uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8765` serves JSON only.
The UI is a Next.js app in `app/` (`npm run dev`, bound to `127.0.0.1:3000`). Next.js rewrites `/api/*` to `JOBHUNT_API_URL` (default `http://127.0.0.1:8765`), so the browser talks to one origin and FastAPI needs no CORS. FastAPI's OpenAPI document is the contract for `lib/api.ts`.

| API route | Purpose | UI page |
|---|---|---|
| `GET /api/jobs?q&where&remote&source&posted_within&has_salary&include_closed&fit&min_score&min_experience&sort&page` | `{jobs, total, page, pages, page_size}`; `fit` is `bank` (default) or `resume`; `sort=newest` is the default (`oldest`, `fit_desc`, `fit_asc`; `sort=match` is the high-to-low fit alias). `q` filters matching jobs before the sort. `min_experience` is 0–15: 0 shows every job, and N shows jobs whose minimum stated years is at least N | Board list |
| `GET /api/jobs/{id}` | Job with `description_md`, `postings`, `events`, `tailor_prompt`, `top_brags`, `gaps`, `coverage` | Board detail pane, mobile sheet |
| `POST /api/jobs/{id}/events` | JSON `{status, reason?}`; status ∈ saved, skipped, applied, removed; returns the job. `removed` drops the job from the tracker and clears its `ui_action` label | Save / skip (with reason) / applied / remove |
| `POST /api/jobs/events/bulk` | JSON `{job_ids, status, reason?}`; 1–300 ids; unknown ids are skipped; `{updated}` | Tracker drag, bulk remove |
| `GET /api/facets` | Source ids and remote types for filter controls | Board filters |
| `GET /api/tracker` | Jobs with a status, grouped saved / applied / skipped. Each card includes `resume_status`, the latest resume run. Order is `tracker_ranks`, then newest status | Application tracker |
| `POST /api/tracker/order` | JSON `{saved, applied, skipped}` of job ids, at most 300 in total. Writes `tracker_ranks` and moves a job when its column changed | Application tracker |
| `GET /api/runs` | Recent runs with counts and errors | Runs |
| `GET/POST /api/brag-docs`, `GET/PUT/DELETE /api/brag-docs/{id}`, `GET /api/brag-docs/companies` | Brag docs, with tags, metrics, and attachments | Brag Docs |
| `GET/POST /api/tags`, `GET/POST /api/metric-keys` | Create is idempotent on a case-insensitive name | Brag Docs form |
| `GET/PUT /api/profile/summary` | Profile body | Profile |
| `GET/POST /api/resumes`, `POST /api/resumes/{id}/select`, `DELETE /api/resumes/{id}` | Resume text; upload is multipart, 5 MB, pdf/md/txt/json | Profile |
| `GET/POST/PUT/DELETE /api/fit/schedules` | Cron schedules; invalid cron, timezone, or a gap under 15 min returns 422 | Schedules |
| `POST /api/fit/schedules/{id}/run` | Queues a run and returns 202; the worker picks it up | Schedules |
| `GET /api/fit/runs`, `GET /api/fit/runs/{id}` | Run list, and one run with its latest progress | Schedules |
| `GET /api/fit/runs/{id}/stream` | SSE: replay `fit_run_events`, then tail `LISTEN/NOTIFY`; `Last-Event-ID` resumes | Schedules |
| `GET /api/fit/status` | Model id, scored counts per mode, stale flag, worker heartbeat | Board, Schedules |
| `POST /api/jobs/{id}/resume` | Queues a resume run; 202 `{run_id}`; 409 when the job has no fit matches. A second click while that job is queued returns the same run | Board detail, Generate resume |
| `POST /api/resume-runs/bulk` | Queues runs for jobs that have no resume yet. Skips a job that already has a finished or active run, or that is unscored. `{queued, skipped}` | Tracker bulk Generate resume |
| `GET /api/jobs/{id}/resume-runs` | Resume runs for one job, latest first | Board detail |
| `GET /api/resume-queue` | Active runs in queue order (`ahead` is how many are in front) and the latest finished runs, with job title and company | Resume queue |
| `GET /api/resume-runs/{id}` | One run. A queued run includes `ahead` | Board detail |
| `GET /api/resume-runs/{id}/stream` | SSE of `resume_run_events`, then `LISTEN/NOTIFY` | Board detail |
| `GET /api/resume-runs/{id}/pdf` | The generated PDF | Board detail download |
| `GET /api/admin/usage?days=` | Token and cost totals, not linked from the header | `/admin/usage` |
| Later: `/api/rules*`, `/api/scopes*`, `/api/companies`, `/api/calibrate` | Same purposes as before (builders, previews, run now, review, labels) | Rules, Scopes, Companies, Calibrate |

Every job carries `score` (0–100) and `fit_tier` (strong / good / fair / low) from `job_fits` for the active model and the latest source of the requested mode whose `scored_at` is set, so the board keeps showing the previous scores while a new run is in progress. Both are `null` until the first fit run, and the card then shows "Not scored yet". `matched_terms` and `missing_terms` come from the same row. Money in API responses is a string so it stays exact. Job description Markdown is rendered in the browser with raw HTML skipped.

**Board card:** title, company, location + remote pill, salary (original currency), age ("3d"), source pills, score badge ("86% Strong", colored by tier). Unscored jobs show "Not scored yet". The detail pane shows the score, its source (brag docs or resume), and the matched and missing terms.

**Detail:** full JD (Markdown rendered, must-have `jd_quote`s highlighted), criteria table (label, JD quote, bank ids, evidence_ok), all source URLs, apply link, status history, "Copy tailor prompt".

**Filters panel:** Match group (score against: brag docs or selected resume; minimum score: any, 40+, 60+, 80+), source, remote type, posted within, salary listed, include closed, text search, location, sort (newest by default, oldest, job fit high to low, job fit low to high). A text query limits the list to matching jobs, then the chosen sort reorders that list.

**Application tracker** (`/tracker`, and `/pipeline` redirects here): three columns (saved, applied, not interested). Drag a card to reorder it in its column, or onto another column to move it. Dragging one card from a selection moves the whole selection. The order is kept in `tracker_ranks`. Each card has a checkbox, and each column has select-all. The selection toolbar queues **Generate resume** for jobs that have no finished resume, and **Remove from tracker** (with undo). Removing appends a `removed` event, so the job leaves the tracker and shows as unsaved on the board. Its history stays.

**Brag Docs page** (`/brag-docs`): the feed groups brag docs by `quarter`, newest first. A sticky filter bar searches title, description, and metric values, filters by every selected tag, one company, and one metric key. "Log a brag doc" is a dialog: title, date (defaults to today, shows the derived quarter), company (creatable), role, impact (1–5, optional), tags (creatable multi-select), metric rows (creatable key plus a value), a growing markdown description, and URL attachments. Typing a new tag or metric key creates it and applies it immediately. Saving on Cmd+Enter.

**Profile page** (`/profile`): the profile summary, and resumes (upload, select exactly one, preview the extracted text, delete). A link points to `/brag-docs`.

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

DELETE FROM runs WHERE started_at < now() - interval '180 days';
```
Then record `pg_database_size(current_database())` for `/runs`. Warn in tick output and on `/runs` at ≥ 70% of 1 GB.

---

## 16. MCP server (`mcp_server.py`)

`jobhunt mcp` starts a FastMCP stdio server named `jobhunt`.

| Tool | Args | Returns |
|---|---|---|
| `search_jobs` | simple filters, `limit≤50` | compact rows: id, title, company, location, score, fit_tier, status, url |
| `get_job` | `job_id` | full job, postings, fit, status history |
| `run_scope` | `scope_id` | run summary (respects lock + guardrail) |
| `list_scopes` / `save_scope` | scope (saved **paused**) | |
| `set_status` | `job_id, status, note?` | event row (origin `claude`) |
| `stats` | — | counts per source, stage, and fit tier; DB size; last runs |

`next_to_score`, `save_assessment`, `list_rules`, `save_rule`, and `digest` belonged to the dropped rubric. They are not tools.

Claude Desktop / Cowork config snippet for README (no secrets inline):

```json
{"mcpServers": {"jobhunt": {
  "command": "/bin/zsh",
  "args": ["-lc", "cd ~/code/jobhunt && op run --env-file=.env.tpl -- uv run jobhunt mcp"]
}}}
```

**Morning digest prompt** (README, for a Cowork scheduled task, weekdays 08:00):
> Use the jobhunt tools. Call `search_jobs` for open jobs scored strong or good that are not saved yet. Give me the top 10: score, fit tier, company, role, location, and the job id.

**Resume generation** ([ADR-0005](docs/adr/0005-resume-agent.md), [ADR-0010](docs/adr/0010-resume-worker-processes.md)): the job detail pane has **Generate resume**. It queues `resume_runs`. The button stays enabled on other jobs while one run is in progress; a job that is already queued or running stays grey. `/resume-queue` lists the queue and recent finished runs. Resume generation is its own process, `jobhunt resume worker`, not a thread inside `jobhunt serve`. Docker Compose and `make api` start `RESUME_WORKERS` of them (default 3). Each process wakes on `NOTIFY resume_runs` (30 second fallback), claims one row, and runs the Claude Agent SDK (`claude-haiku-5-5` by default) with the server skill `tailor-resume-server`. A run whose worker dies is claimed again until `claims` reaches 3, then it is marked failed. Input is the job description, the fit shortlist, and other brag docs ordered by `impact` (1–5) then similarity. The same fit model then checks that the resume scores at least as high as the shortlist and still covers those requirements. Up to two rewrites get the gaps as feedback. The PDF, `resume.json`, and lint report are stored on the run. Each attempt writes an `agent_usage` row (tokens and USD, no prompt text) shown on `/admin/usage`. A run stops retrying after `RESUME_MAX_COST_USD` (default 5). The worker reads only Postgres, the synced kit, and the environment, so hosting it later does not change the code. The app writes to the vault only through `jobhunt brag-docs migrate-vault --write` ([ADR-0002](docs/adr/0002-brag-docs.md)).

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
  *Accept:* sanitized profile contains no brag doc titles/metrics/description (test asserts); hash stable across runs.
- **T2.2–T2.6** The filter DSL, prefilter, rubric, and rules tasks were not built. Dropped in [ADR-0011](docs/adr/0011-fit-replaces-rubric.md).
- **T2.7 Job fit schema + model** (§13.8). Tables, `JobFitModel`, BGE strategy, fake strategy, registry, keyword matching.
  *Accept:* calibration clamps to 0–100; a second `run_fit` scores nothing; editing the bank changes the source hash and the next run rescores.
- **T2.8 Fit worker** (§13.8). Claim with `SKIP LOCKED`, idempotency key, per-batch progress plus `pg_notify`, resume after a crash, SIGTERM, heartbeat.
  *Accept:* two workers claiming at once take different runs; a killed run resumes and scores only the remaining jobs; the SSE stream replays history, resumes from `Last-Event-ID` with no duplicates, and ends on the final status event.
- **T2.9 Profile + schedules API** (§14). Entry and resume CRUD, schedule validation (422 on bad cron, timezone, or a gap under 15 min), queue run returns 202, fit status with the stale flag.
  *Accept:* integration tests cover each route; the board's `sort=fit_desc` (`sort=match` alias) and `min_score` read stored scores only.
- **T2.10 Profile + schedules UI.** `/profile`, `/schedules` with live progress, the match filter group, the score badge, and the scoring pill.
  *Accept:* Playwright covers the board sorted by score, a schedule edit, and a run whose progress survives a reload.
- **T2.11 Brag docs** ([ADR-0002](docs/adr/0002-brag-docs.md)). Replace `bank_entries` with tags, metric keys, brag docs, and their metrics and attachments. `/brag-docs` with the creatable form, quarter grouping, and the filter bar. `jobhunt brag-docs migrate-vault` rewrites old vault frontmatter once.
  *Accept:* `2026-10-08` stores `Q4 2026`; creating a tag or metric key twice returns the same row; a metric filter shows only docs that use that key; the vault rewrite leaves the body unchanged and is a no-op the second time.

### P3 — UI and orchestration (week 4)

- **T3.1 Web skeleton** (app factory, base template, static, 127.0.0.1 bind).
- **T3.2 Board + detail + events** (§14).
  *Accept:* filter changes update results without full reload; URL reflects filters; save/skip writes `job_events` and `labels`.
- **T3.3** Saved rules are dropped with the rubric ([ADR-0011](docs/adr/0011-fit-replaces-rubric.md)).
- **T3.4 Scopes builder + schedule preview + run now.**
  *Accept:* guardrail error shown inline; run now respects lock.
- **T3.5 Runs, companies review, calibrate pages.**
- **T3.6 MCP remaining tools** (`run_scope`, scopes saved paused, `set_status`) + README for Cowork config.
  *Accept:* `set_status` writes a `job_events` row with origin `claude`.
- **T3.7 Retention** (§15) in tick + size warning.
  *Accept:* integration test with backdated rows.

### Later (not v1)
HN / RemoteOK / Remotive adapters (P2-ready interfaces exist), Glassdoor/ZipRecruiter, cover letters from the bank, hosted UI behind login.

---

## 18. Testing strategy

- **Unit:** normalizers, schedule, fit score. Pure, fast, table-driven.
- **Adapter:** respx/CSV fixtures only; live tests opt-in with `-m live`.
- **Integration:** Docker Postgres from `docker-compose.test.yml`, `TEST_DATABASE_URL` (no secrets; local only). Migrate once per session; each test in a rolled-back transaction.
- **E2E:** fake adapter → `tick` → match → `save_assessment` with a canned Assessment → rule hit → digest.
- Coverage target 85% on `jobhunt/` and `api/`.

---

## 19. Decisions still open (defaults in place)

| Decision | Default used | Where to change |
|---|---|---|
| Target locations, remote tz band | SG + TH onsite/hybrid; remote overlapping UTC+5..+10 | `config/prefs.yaml` |
| First 30 companies | none; San fills `companies.seed.yaml` (name + careers URL; detector finds ATS) | `config/companies.seed.yaml` |
| Initial fetch scopes | ATS tiers A+B daily 07:00; scheduled software-role searches include `software engineer`, `product engineer`, `growth engineer`, and `web engineer`; Indeed for SG, TH, TW, JP, AU, NZ, HK, MY, VN, ID, UK, DE, NL, FR daily 07:30; LinkedIn guest SG at 08:00 and 20:00, plus one daily search per new country from 09:00; Glassdoor SG/AU/NZ; Naukri Bengaluru; Adzuna gb/de/nl/fr/au/nz/sg/in; Reed London; Jooble for those countries except VN; MyCareersFuture SG | `config/scopes.seed.yaml` or UI |
| Write shortlisted jobs to Obsidian | no (vault stays read-only) | revisit after v1 |

`companies.seed.yaml` format:

```yaml
- name: <Company>
  careers_url: https://<company>/careers
  tier: A            # A dream, B good, C backup
  # ats / ats_slug filled by `jobhunt companies detect`
```
