FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# dbmate is downloaded with Python so the image does not need apt.
# apt on this network fails signature checks behind the TLS gateway.
RUN python -c "import os,stat,urllib.request; m='arm64' if os.uname().machine in {'aarch64','arm64'} else 'amd64'; urllib.request.urlretrieve(f'https://github.com/amacneil/dbmate/releases/download/v2.36.0/dbmate-linux-{m}', '/usr/local/bin/dbmate'); os.chmod('/usr/local/bin/dbmate', 0o755)"

COPY pyproject.toml uv.lock README.md ./
COPY jobhunt jobhunt
COPY db db
COPY config config
COPY schema.sql ./

# Empty keeps the API image slim. "fit" adds CPU torch for the worker.
ARG FIT_EXTRA=
RUN if [ -n "$FIT_EXTRA" ]; then uv sync --frozen --no-dev --extra "$FIT_EXTRA"; else uv sync --frozen --no-dev; fi

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8765

CMD ["sh", "-c", "mkdir -p /tmp/jobhunt-bank && jobhunt db migrate up && jobhunt seed && jobhunt serve --host 0.0.0.0 --port 8765"]
