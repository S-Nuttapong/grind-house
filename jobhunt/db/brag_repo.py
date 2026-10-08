"""SQL for brag docs, tags, and metric keys. Callers pass an open connection."""

import re
import zlib
from typing import Any

from psycopg import Connection

TAG_COLORS = (
    "#3B82F6",
    "#10B981",
    "#F59E0B",
    "#EF4444",
    "#8B5CF6",
    "#EC4899",
    "#14B8A6",
    "#F97316",
)

_LIST = """
SELECT
    d.id, d.title, d.date, d.quarter, d.company, d.role, d.description_md,
    d.origin, d.updated_at,
    COALESCE(tag_rows.tags, '[]'::jsonb) AS tags,
    COALESCE(metric_rows.metrics, '[]'::jsonb) AS metrics,
    COALESCE(attachment_rows.attachments, '[]'::jsonb) AS attachments
FROM brag_docs d
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object('id', t.id, 'name', t.name, 'color_hex', t.color_hex)
        ORDER BY lower(t.name)
    ) AS tags
    FROM brag_doc_tags dt
    JOIN tags t ON t.id = dt.tag_id
    WHERE dt.brag_doc_id = d.id
) tag_rows ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', m.id, 'metric_key_id', m.metric_key_id, 'name', k.name,
            'value', m.value, 'position', m.position
        )
        ORDER BY m.position
    ) AS metrics
    FROM brag_doc_metrics m
    JOIN metric_keys k ON k.id = m.metric_key_id
    WHERE m.brag_doc_id = d.id
) metric_rows ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(
        jsonb_build_object('id', a.id, 'type', a.type, 'link', a.link, 'position', a.position)
        ORDER BY a.position
    ) AS attachments
    FROM brag_doc_attachments a
    WHERE a.brag_doc_id = d.id
) attachment_rows ON true
"""


def color_for(name: str) -> str:
    index = zlib.crc32(name.strip().lower().encode()) % len(TAG_COLORS)
    return TAG_COLORS[index]


def list_brag_docs(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(_LIST + " ORDER BY d.date DESC, d.id DESC")
        return list(cursor.fetchall())


def get_brag_doc(conn: Connection[Any], doc_id: str) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(_LIST + " WHERE d.id = %s", (doc_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def save_brag_doc(conn: Connection[Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace a brag doc and its tags, metrics, and attachments."""
    conn.execute(
        """
        INSERT INTO brag_docs (id, title, date, company, role, description_md, origin)
        VALUES (%(id)s, %(title)s, %(date)s, %(company)s, %(role)s, %(description_md)s, %(origin)s)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title, date = EXCLUDED.date, company = EXCLUDED.company,
            role = EXCLUDED.role, description_md = EXCLUDED.description_md,
            origin = EXCLUDED.origin, updated_at = now()
        """,
        doc,
    )
    conn.execute("DELETE FROM brag_doc_tags WHERE brag_doc_id = %s", (doc["id"],))
    conn.execute("DELETE FROM brag_doc_metrics WHERE brag_doc_id = %s", (doc["id"],))
    conn.execute("DELETE FROM brag_doc_attachments WHERE brag_doc_id = %s", (doc["id"],))
    for tag_id in dict.fromkeys(doc["tag_ids"]):
        conn.execute(
            "INSERT INTO brag_doc_tags (brag_doc_id, tag_id) VALUES (%s, %s)",
            (doc["id"], tag_id),
        )
    for position, metric in enumerate(doc["metrics"], start=1):
        conn.execute(
            """
            INSERT INTO brag_doc_metrics (brag_doc_id, metric_key_id, value, position)
            VALUES (%s, %s, %s, %s)
            """,
            (doc["id"], metric["metric_key_id"], metric["value"], position),
        )
    for position, attachment in enumerate(doc["attachments"], start=1):
        conn.execute(
            """
            INSERT INTO brag_doc_attachments (brag_doc_id, type, link, position)
            VALUES (%s, %s, %s, %s)
            """,
            (doc["id"], attachment["type"], attachment["link"], position),
        )
    stored = get_brag_doc(conn, str(doc["id"]))
    if stored is None:
        raise RuntimeError("save_brag_doc lost the row")
    return stored


def delete_brag_doc(conn: Connection[Any], doc_id: str) -> bool:
    deleted = conn.execute("DELETE FROM brag_docs WHERE id = %s", (doc_id,)).rowcount
    return deleted > 0


def next_brag_doc_id(conn: Connection[Any]) -> str:
    highest = 0
    for (doc_id,) in conn.execute("SELECT id FROM brag_docs").fetchall():
        match = re.fullmatch(r"BB-(\d+)", str(doc_id))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"BB-{highest + 1:03d}"


def list_tags(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT id, name, color_hex FROM tags ORDER BY lower(name)")
        return list(cursor.fetchall())


def get_or_create_tag(
    conn: Connection[Any], name: str, color_hex: str | None = None
) -> tuple[dict[str, Any], bool]:
    cleaned = name.strip()
    color = color_hex or color_for(cleaned)
    row = conn.execute(
        """
        INSERT INTO tags (name, color_hex)
        VALUES (%s, %s)
        ON CONFLICT ((lower(name))) DO NOTHING
        RETURNING id, name, color_hex
        """,
        (cleaned, color),
    ).fetchone()
    if row is not None:
        return {"id": int(row[0]), "name": str(row[1]), "color_hex": str(row[2])}, True
    existing = conn.execute(
        "SELECT id, name, color_hex FROM tags WHERE lower(name) = lower(%s)",
        (cleaned,),
    ).fetchone()
    if existing is None:
        raise RuntimeError("get_or_create_tag lost the row")
    return {"id": int(existing[0]), "name": str(existing[1]), "color_hex": str(existing[2])}, False


def list_metric_keys(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT id, name FROM metric_keys ORDER BY lower(name)")
        return list(cursor.fetchall())


def get_or_create_metric_key(conn: Connection[Any], name: str) -> tuple[dict[str, Any], bool]:
    cleaned = name.strip()
    row = conn.execute(
        """
        INSERT INTO metric_keys (name)
        VALUES (%s)
        ON CONFLICT ((lower(name))) DO NOTHING
        RETURNING id, name
        """,
        (cleaned,),
    ).fetchone()
    if row is not None:
        return {"id": int(row[0]), "name": str(row[1])}, True
    existing = conn.execute(
        "SELECT id, name FROM metric_keys WHERE lower(name) = lower(%s)",
        (cleaned,),
    ).fetchone()
    if existing is None:
        raise RuntimeError("get_or_create_metric_key lost the row")
    return {"id": int(existing[0]), "name": str(existing[1])}, False


def list_companies(conn: Connection[Any]) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT company FROM brag_docs
        WHERE company IS NOT NULL AND company <> ''
        ORDER BY company
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def tags_exist(conn: Connection[Any], tag_ids: list[int]) -> bool:
    return _ids_exist(conn, "tags", tag_ids)


def metric_keys_exist(conn: Connection[Any], key_ids: list[int]) -> bool:
    return _ids_exist(conn, "metric_keys", key_ids)


def _ids_exist(conn: Connection[Any], table: str, ids: list[int]) -> bool:
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return True
    if table not in {"tags", "metric_keys"}:
        raise ValueError(f"unsupported id table: {table}")
    row = conn.execute(f"SELECT count(*) FROM {table} WHERE id = ANY(%s)", (wanted,)).fetchone()
    found = 0 if row is None else int(row[0])
    return found == len(wanted)


def _dict_row(cursor: Any) -> Any:
    from psycopg.rows import dict_row

    return dict_row(cursor)
