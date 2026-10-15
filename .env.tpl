# Copy this file to .env and fill in the values. .env is gitignored. Do not commit it.
# Quote a value if it contains spaces.

# Local Postgres from `docker compose` or Postgres.app.
DATABASE_URL=postgresql://jobhunt:jobhunt@127.0.0.1:54330/jobhunt?sslmode=disable

# Folder of brag-bank markdown.
VAULT_BANK_PATH=

# Required for resume generation and Claude scoring.
ANTHROPIC_API_KEY=

# Optional board APIs. Leave a value blank to skip that source.
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
REED_API_KEY=
# JSON object of ISO country code to that country's Jooble key. One key per host.
JOOBLE_API_KEYS=

# Set to 1 to allow scoring and resume text to leave this machine.
JOBHUNT_ALLOW_OFFSITE=1

# How many resume worker processes `make api` and Docker Compose start. Default 3.
# RESUME_WORKERS=3
# Writer model. Code and Compose default to claude-opus-5-5 when this is unset.
# RESUME_MODEL=claude-haiku-5-5
# Claude CLI path when the bundled CLI cannot run, for example on a CPU without AVX.
# RESUME_CLI=
