"""SQL for the profile: bank summary and uploaded resumes. Callers pass an open connection."""

from typing import Any

from psycopg import Connection


def get_bank_profile(conn: Connection[Any]) -> str:
    row = conn.execute("SELECT body_md FROM bank_profile").fetchone()
    return "" if row is None else str(row[0])


def set_bank_profile(conn: Connection[Any], body_md: str) -> None:
    conn.execute("UPDATE bank_profile SET body_md = %s, updated_at = now()", (body_md,))


def insert_resume(
    conn: Connection[Any], *, name: str, text: str, filename: str | None, origin: str
) -> int:
    row = conn.execute(
        """
        INSERT INTO resumes (name, text, filename, origin)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (name, text, filename, origin),
    ).fetchone()
    if row is None:
        raise RuntimeError("insert_resume returned no id")
    return int(row[0])


def list_resumes(conn: Connection[Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, name, filename, text, origin, is_selected, created_at,
                   length(text) AS text_length
            FROM resumes ORDER BY id
            """
        )
        return list(cursor.fetchall())


def get_resume(conn: Connection[Any], resume_id: int) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM resumes WHERE id = %s", (resume_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def select_resume(conn: Connection[Any], resume_id: int) -> bool:
    conn.execute("UPDATE resumes SET is_selected = false WHERE is_selected")
    updated = conn.execute(
        "UPDATE resumes SET is_selected = true WHERE id = %s", (resume_id,)
    ).rowcount
    return updated > 0


def delete_resume(conn: Connection[Any], resume_id: int) -> bool:
    deleted = conn.execute("DELETE FROM resumes WHERE id = %s", (resume_id,)).rowcount
    return deleted > 0


def selected_resume(conn: Connection[Any]) -> dict[str, Any] | None:
    with conn.cursor(row_factory=_dict_row) as cursor:
        cursor.execute("SELECT * FROM resumes WHERE is_selected")
        row = cursor.fetchone()
    return dict(row) if row else None


def _dict_row(cursor: Any) -> Any:
    from psycopg.rows import dict_row

    return dict_row(cursor)
