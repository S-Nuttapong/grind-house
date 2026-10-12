from pathlib import Path

import psycopg
import pytest
from jobhunt.core.migrate import migrate

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "db" / "migrations" / "20261009000004_brag_docs.sql"
)

_BANK_ENTRIES = """
CREATE TABLE bank_entries (
  id            text PRIMARY KEY,
  title         text NOT NULL,
  company       text,
  role          text,
  period        text,
  my_role       text,
  scope         text,
  metrics       jsonb NOT NULL DEFAULT '[]',
  strength      smallint,
  confidential  boolean NOT NULL DEFAULT false,
  status        text NOT NULL DEFAULT 'draft',
  tags          text[] NOT NULL DEFAULT '{}',
  body_md       text NOT NULL DEFAULT '',
  origin        text NOT NULL DEFAULT 'ui',
  updated_at    timestamptz NOT NULL DEFAULT now()
)
"""


@pytest.mark.integration
def test_migrate_up_down_up_leaves_sources(database_url: str) -> None:
    """The session fixture already cycled up/down/up. Sources from the seed remain."""
    with psycopg.connect(database_url) as connection:
        row = connection.execute("SELECT count(*) FROM sources").fetchone()
    assert row is not None
    assert row[0] == 16


def test_migrate_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        migrate("sideways")


def test_brag_docs_migration_copies_entries(conn: psycopg.Connection) -> None:
    conn.execute("SET TIME ZONE 'UTC'")
    conn.execute(
        "DROP TABLE brag_doc_attachments, brag_doc_metrics, brag_doc_tags, brag_docs, "
        "metric_keys, tags"
    )
    conn.execute(_BANK_ENTRIES)
    conn.execute(
        """
        INSERT INTO bank_entries (
          id, title, company, role, period, metrics, tags, body_md, updated_at
        )
        VALUES
          (
            'BB-010', 'Faster home page', 'EarnIn', 'Engineer', '2025-08 – 2025-09',
            '[
              {"kind":"page-experience","text":"P90 LCP 6s to 1.5s"},
              {"text":"retries -38%"}
            ]'::jsonb,
            ARRAY['skill/go', 'Backend'], 'Led the migration.', '2026-01-15 00:00+00'
          ),
          (
            'BB-011', 'Undated', NULL, NULL, 'not-a-date', '[]'::jsonb, '{}',
            'No period.', '2026-10-08 12:00+00'
          )
        """
    )
    up = _MIGRATION.read_text().split("-- migrate:down", 1)[0].split("-- migrate:up", 1)[1]
    with psycopg.ClientCursor(conn) as cursor:
        cursor.execute(up)

    dated = conn.execute(
        "SELECT date::text, quarter, description_md, company FROM brag_docs WHERE id = 'BB-010'"
    ).fetchone()
    assert dated == ("2025-09-30", "Q3 2025", "Led the migration.", "EarnIn")
    undated = conn.execute(
        "SELECT date::text, quarter FROM brag_docs WHERE id = 'BB-011'"
    ).fetchone()
    assert undated == ("2026-10-08", "Q4 2026")

    tags = conn.execute(
        """
        SELECT tags.name FROM brag_doc_tags
        JOIN tags ON tags.id = brag_doc_tags.tag_id
        WHERE brag_doc_id = 'BB-010'
        ORDER BY tags.name
        """
    ).fetchall()
    assert [row[0] for row in tags] == ["Backend", "skill/go"]

    metrics = conn.execute(
        """
        SELECT metric_keys.name, brag_doc_metrics.value
        FROM brag_doc_metrics
        JOIN metric_keys ON metric_keys.id = brag_doc_metrics.metric_key_id
        WHERE brag_doc_id = 'BB-010'
        ORDER BY brag_doc_metrics.position
        """
    ).fetchall()
    assert metrics == [("Page Experience", "P90 LCP 6s to 1.5s"), ("General", "retries -38%")]
    gone = conn.execute("SELECT to_regclass('public.bank_entries')").fetchone()
    assert gone is not None
    assert gone[0] is None
