FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && arch="$(uname -m)" \
    && case "$arch" in aarch64|arm64) machine=arm64 ;; *) machine=amd64 ;; esac \
    && curl -fsSL -o /usr/local/bin/dbmate \
      "https://github.com/amacneil/dbmate/releases/download/v2.36.0/dbmate-linux-${machine}" \
    && chmod +x /usr/local/bin/dbmate \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY jobhunt jobhunt
COPY db db
COPY config config
COPY schema.sql ./

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8765

CMD ["sh", "-c", "mkdir -p /tmp/jobhunt-bank && jobhunt db migrate up && jobhunt seed && jobhunt serve --host 0.0.0.0 --port 8765"]
