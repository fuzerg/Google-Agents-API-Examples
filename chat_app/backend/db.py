"""SQLite persistence for conversations and messages.

Uses the stdlib sqlite3 module with a thread-safe connection per call. The
schema is intentionally simple: conversations own an ordered list of messages,
and each conversation tracks the last interaction id for multi-turn chaining
via the Interactions API's previous_interaction_id.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    agent               TEXT,
    model               TEXT NOT NULL,
    project             TEXT,
    last_interaction_id TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    interaction_id  TEXT,
    status          TEXT NOT NULL DEFAULT 'complete',
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist and run lightweight migrations."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Migration: add `project` to older conversations tables if missing.
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(conversations)").fetchall()
        }
        if "project" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN project TEXT")


# --------------------------------------------------------------------------- #
# App settings (key/value)
# --------------------------------------------------------------------------- #
def get_setting(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None


def set_setting(key: str, value: str | None) -> None:
    with _connect() as conn:
        if value is None:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


# --------------------------------------------------------------------------- #
# Conversations
# --------------------------------------------------------------------------- #
def create_conversation(
    *, title: str, agent: str | None, model: str, project: str | None = None
) -> dict[str, Any]:
    conv_id = _new_id()
    ts = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations
                (id, title, agent, model, project, last_interaction_id,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (conv_id, title, agent, model, project, ts, ts),
        )
    return get_conversation(conv_id)  # type: ignore[return-value]


def list_conversations() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_conversation(conv_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        return dict(row) if row else None


def list_recent_projects(limit: int = 10) -> list[str]:
    """Return distinct projects used by conversations, most-recent first."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT project, MAX(updated_at) AS last_used
            FROM conversations
            WHERE project IS NOT NULL AND project != ''
            GROUP BY project
            ORDER BY last_used DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [r["project"] for r in rows]


def rename_conversation(conv_id: str, title: str) -> dict[str, Any] | None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _now(), conv_id),
        )
    return get_conversation(conv_id)


def delete_conversation(conv_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        return cur.rowcount > 0


def touch_conversation(
    conv_id: str, *, last_interaction_id: str | None = None
) -> None:
    with _connect() as conn:
        if last_interaction_id is not None:
            conn.execute(
                "UPDATE conversations SET updated_at = ?, last_interaction_id = ? "
                "WHERE id = ?",
                (_now(), last_interaction_id, conv_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_now(), conv_id),
            )


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
def add_message(
    *,
    conversation_id: str,
    role: str,
    content: str,
    interaction_id: str | None = None,
    status: str = "complete",
) -> dict[str, Any]:
    msg_id = _new_id()
    ts = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO messages
                (id, conversation_id, role, content, interaction_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, conversation_id, role, content, interaction_id, status, ts),
        )
    return get_message(msg_id)  # type: ignore[return-value]


def update_message(
    msg_id: str,
    *,
    content: str | None = None,
    interaction_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = []
    if content is not None:
        sets.append("content = ?")
        params.append(content)
    if interaction_id is not None:
        sets.append("interaction_id = ?")
        params.append(interaction_id)
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if not sets:
        return get_message(msg_id)
    params.append(msg_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE messages SET {', '.join(sets)} WHERE id = ?", params
        )
    return get_message(msg_id)


def get_message(msg_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (msg_id,)
        ).fetchone()
        return dict(row) if row else None


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def clear_conversation_messages(conversation_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute(
            "UPDATE conversations SET last_interaction_id = NULL, updated_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )
