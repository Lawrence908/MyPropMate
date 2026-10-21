"""Portfolio tables: properties, household tasks, leasing (prospects, messages,
listing posts) and reusable message templates.

These live in the same SQLite file as the receipt pipeline but are owned by the
web UI, not by ``tenants.json``. Every row hangs off a ``property_id`` so the
app can manage more than one house.

The receipt tables are untouched apart from one nullable column,
``tenants.property_id``. ``upsert_tenant`` never writes it, so the property a
tenant belongs to is DB-owned (set from the UI) and survives the constant
re-seed from JSON, the same way the invoice counter does.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,               -- short label, e.g. "Wainwright house"
    address     TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    province    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'rented',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id  INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    code         TEXT NOT NULL DEFAULT '',    -- e.g. "A1" from a scope of work
    title        TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'maintenance',
    grp          TEXT NOT NULL DEFAULT '',    -- grouping, e.g. "Priority A"
    status       TEXT NOT NULL DEFAULT 'todo',
    due_date     TEXT NOT NULL DEFAULT '',    -- ISO date or ''
    assignee     TEXT NOT NULL DEFAULT '',    -- vendor or person
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prospects (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id      INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    channel          TEXT NOT NULL DEFAULT 'facebook',
    contact          TEXT NOT NULL DEFAULT '',  -- email, phone, or profile URL
    source           TEXT NOT NULL DEFAULT '',  -- "personal contact", a post, a referral
    status           TEXT NOT NULL DEFAULT 'to_contact',
    personal_note    TEXT NOT NULL DEFAULT '',  -- the personal blurb that opens a message
    notes            TEXT NOT NULL DEFAULT '',
    last_contact_at  TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id  INTEGER NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
    direction    TEXT NOT NULL DEFAULT 'out',   -- out | in
    channel      TEXT NOT NULL DEFAULT 'facebook',
    subject      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft', -- draft | sent | received
    created_at   TEXT NOT NULL,
    sent_at      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id  INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    venue        TEXT NOT NULL,                 -- "Wainwright Rentals (FB group)"
    venue_type   TEXT NOT NULL DEFAULT 'fb_group',
    venue_url    TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft', -- draft | ready | posted | closed
    posted_at    TEXT NOT NULL DEFAULT '',
    post_url     TEXT NOT NULL DEFAULT '',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id  INTEGER REFERENCES properties(id) ON DELETE CASCADE, -- NULL = any property
    name         TEXT NOT NULL,
    channel      TEXT NOT NULL DEFAULT 'facebook',
    subject      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

# Allowed values, served to the UI from /api/meta so both sides agree.
PROPERTY_STATUSES = ["rented", "vacant", "preparing_sale", "listed", "sold", "buying"]
TASK_STATUSES = ["todo", "doing", "waiting", "done", "skipped"]
TASK_CATEGORIES = ["maintenance", "vendor", "admin", "leasing", "sale", "purchase"]
PROSPECT_STATUSES = [
    "to_contact", "contacted", "replied", "interested", "viewing",
    "applied", "approved", "signed", "declined", "not_interested",
]
CHANNELS = ["facebook", "email", "text", "phone", "other"]
POST_STATUSES = ["draft", "ready", "posted", "closed"]
VENUE_TYPES = ["fb_group", "fb_marketplace", "website", "kijiji", "bulletin", "other"]

# Writable columns per table. Anything else in a request body is ignored.
FIELDS: Dict[str, List[str]] = {
    "properties": ["name", "address", "city", "province", "status", "notes"],
    "tasks": ["property_id", "code", "title", "category", "grp", "status",
              "due_date", "assignee", "notes"],
    "prospects": ["property_id", "name", "channel", "contact", "source", "status",
                  "personal_note", "notes", "last_contact_at"],
    "messages": ["prospect_id", "direction", "channel", "subject", "body",
                 "status", "sent_at"],
    "posts": ["property_id", "venue", "venue_type", "venue_url", "title", "body",
              "status", "posted_at", "post_url", "notes"],
    "templates": ["property_id", "name", "channel", "subject", "body"],
}

# Tables without an updated_at column.
_NO_UPDATED_AT = {"messages"}

# Columns that may be cleared to NULL on update (other None values are ignored).
_NULLABLE = {("templates", "property_id")}


def now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tenants)")}
    if cols and "property_id" not in cols:
        conn.execute("ALTER TABLE tenants ADD COLUMN property_id INTEGER REFERENCES properties(id)")
    conn.commit()


def insert(conn: sqlite3.Connection, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: v for k, v in data.items() if k in FIELDS[table] and v is not None}
    row["created_at"] = now()
    if table not in _NO_UPDATED_AT:
        row["updated_at"] = row["created_at"]
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    conn.commit()
    return get(conn, table, cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int,
           data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = {k: v for k, v in data.items()
           if k in FIELDS[table] and (v is not None or (table, k) in _NULLABLE)}
    if table not in _NO_UPDATED_AT:
        row["updated_at"] = now()
    if row:
        sets = ", ".join(f"{k} = ?" for k in row)
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*row.values(), row_id))
        conn.commit()
    return get(conn, table, row_id)


def delete(conn: sqlite3.Connection, table: str, row_id: int) -> bool:
    if table == "properties":
        # Tenants belong to the receipt pipeline and outlive a property record.
        conn.execute("UPDATE tenants SET property_id = NULL WHERE property_id = ?", (row_id,))
    cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    conn.commit()
    return cur.rowcount > 0


def get(conn: sqlite3.Connection, table: str, row_id: int) -> Optional[Dict[str, Any]]:
    r = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(r) if r else None


def list_rows(conn: sqlite3.Connection, table: str, where: Dict[str, Any],
              order: str = "id") -> List[Dict[str, Any]]:
    clauses = [f"{k} = ?" for k in where]
    sql = f"SELECT * FROM {table}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" ORDER BY {order}"
    return [dict(r) for r in conn.execute(sql, tuple(where.values()))]


def render_template(body: str, values: Dict[str, str]) -> str:
    """Fill ``{first_name}``-style placeholders, leaving unknown ones intact."""
    out = body
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def placeholder_values(prospect: Dict[str, Any],
                       prop: Optional[Dict[str, Any]]) -> Dict[str, str]:
    name = (prospect.get("name") or "").strip()
    return {
        "name": name,
        "first_name": name.split(" ")[0] if name else "",
        "personal_note": prospect.get("personal_note") or "",
        "property_name": (prop or {}).get("name", ""),
        "city": (prop or {}).get("city", ""),
    }


def summary(conn: sqlite3.Connection, ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
    """Per-property counts for the overview cards."""
    out: Dict[int, Dict[str, Any]] = {}
    for pid in ids:
        tasks = conn.execute(
            "SELECT status, COUNT(*) n FROM tasks WHERE property_id = ? GROUP BY status", (pid,)
        ).fetchall()
        prospects = conn.execute(
            "SELECT status, COUNT(*) n FROM prospects WHERE property_id = ? GROUP BY status", (pid,)
        ).fetchall()
        posts = conn.execute(
            "SELECT status, COUNT(*) n FROM posts WHERE property_id = ? GROUP BY status", (pid,)
        ).fetchall()
        tenants = conn.execute(
            "SELECT COUNT(*) FROM tenants WHERE property_id = ?", (pid,)
        ).fetchone()[0]
        out[pid] = {
            "tasks": {r["status"]: r["n"] for r in tasks},
            "prospects": {r["status"]: r["n"] for r in prospects},
            "posts": {r["status"]: r["n"] for r in posts},
            "tenants": tenants,
        }
    return out
