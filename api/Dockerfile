FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# dbmate is downloaded with Python so the image does not need apt.
# apt on this network fails signature checks behind the TLS gateway.
RUN python -c "import os,stat,urllib.request; m='arm64' if os.uname().machine in {'aarch64','arm64'} else 'amd64'; urllib.request.urlretrieve(f'https://github.com/amacneil/dbmate/releases/download/v2.36.0/dbmate-linux-{m}', '/usr/local/bin/dbmate'); os.chmod('/usr/local/bin/dbmate', 0o755)"

COPY pyproject.toml uv.lock ./
COPY jobhunt jobhunt
COPY db db
COPY config config
# Vendored wheels. The image cannot reach the package indexes on this
# network: Artifactory times out, and pytorch.org fails the TLS check.
COPY wheels /wheels

# Empty keeps the API image slim. "fit" installs the vendored fit extra.
ARG FIT_EXTRA=
RUN if [ -n "$FIT_EXTRA" ]; then \
      uv venv /app/.venv --python /usr/local/bin/python3 \
        && uv pip install --python /app/.venv/bin/python --offline --no-index --no-deps --find-links /wheels -r /wheels/requirements-fit.txt \
        && uv pip install --python /app/.venv/bin/python --offline --no-index --no-deps --find-links /wheels 'torch==2.2.2' \
        && uv pip install --python /app/.venv/bin/python --offline --no-index --no-deps --find-links /wheels /app \
        && mkdir -p /app/reports \
        && ln -sfn /app/config /app/.venv/lib/python3.12/site-packages/config \
        && ln -sfn /app/db /app/.venv/lib/python3.12/site-packages/db \
        && ln -sfn /app/reports /app/.venv/lib/python3.12/site-packages/reports; \
    else uv sync --frozen --no-dev; fi

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8765

CMD ["sh", "-c", "mkdir -p /tmp/jobhunt-bank && jobhunt db migrate up && jobhunt seed && jobhunt serve --host 0.0.0.0 --port 8765"]
