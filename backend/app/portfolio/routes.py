"""HTTP routes for the portfolio UI: properties, tasks, leasing, templates.

Outbound messages follow the same rule as receipts: nothing leaves without an
explicit action. A message is created as a ``draft``; ``/send`` emails it when
the channel is email and the prospect has an address, and for every other
channel (Facebook, text) it only records that you sent it yourself.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.config import Settings, get_settings
from app.pipeline.store import Store
from app.portfolio import store as ps

router = APIRouter(prefix="/api")


def get_conn(settings: Settings = Depends(get_settings)):
    st = Store(settings.db_path)
    try:
        ps.ensure_schema(st.conn)
        yield st.conn
    finally:
        st.close()


def _check(value: Optional[str], allowed: List[str], field: str) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(422, f"{field} must be one of {allowed}")


def _or_404(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if row is None:
        raise HTTPException(404, "not found")
    return row


def _validate(table: str, data: Dict[str, Any]) -> None:
    if table == "properties":
        _check(data.get("status"), ps.PROPERTY_STATUSES, "status")
    elif table == "tasks":
        _check(data.get("status"), ps.TASK_STATUSES, "status")
        _check(data.get("category"), ps.TASK_CATEGORIES, "category")
    elif table == "prospects":
        _check(data.get("status"), ps.PROSPECT_STATUSES, "status")
        _check(data.get("channel"), ps.CHANNELS, "channel")
    elif table == "posts":
        _check(data.get("status"), ps.POST_STATUSES, "status")
        _check(data.get("venue_type"), ps.VENUE_TYPES, "venue_type")
    elif table == "templates":
        _check(data.get("channel"), ps.CHANNELS, "channel")


def _require(data: Dict[str, Any], *fields: str) -> None:
    missing = [f for f in fields if not data.get(f)]
    if missing:
        raise HTTPException(422, f"missing required field(s): {', '.join(missing)}")


@router.get("/meta")
def meta():
    return {
        "property_statuses": ps.PROPERTY_STATUSES,
        "task_statuses": ps.TASK_STATUSES,
        "task_categories": ps.TASK_CATEGORIES,
        "prospect_statuses": ps.PROSPECT_STATUSES,
        "channels": ps.CHANNELS,
        "post_statuses": ps.POST_STATUSES,
        "venue_types": ps.VENUE_TYPES,
        "placeholders": ["first_name", "name", "personal_note", "property_name", "city"],
    }


@router.get("/overview")
def overview(conn=Depends(get_conn)):
    props = ps.list_rows(conn, "properties", {}, "name")
    counts = ps.summary(conn, [p["id"] for p in props])
    pay = conn.execute(
        "SELECT "
        " SUM(CASE WHEN invoice_no IS NOT NULL AND emailed = 0 THEN 1 ELSE 0 END) pending,"
        " SUM(CASE WHEN invoice_no IS NULL THEN 1 ELSE 0 END) failed,"
        " SUM(CASE WHEN emailed = 1 THEN 1 ELSE 0 END) sent "
        "FROM payments"
    ).fetchone()
    return {
        "properties": [{**p, "counts": counts[p["id"]]} for p in props],
        "payments": {k: pay[k] or 0 for k in ("pending", "failed", "sent")},
    }


# --- generic CRUD -------------------------------------------------------------
# One set of handlers per table keeps the routes uniform. Filters are limited
# to the foreign-key column so arbitrary query params cannot reach SQL.

_PARENT = {"tasks": "property_id", "prospects": "property_id", "posts": "property_id",
           "templates": "property_id"}
_REQUIRED = {"properties": ("name",), "tasks": ("property_id", "title"),
             "prospects": ("property_id", "name"), "posts": ("property_id", "venue"),
             "templates": ("name", "body")}
_ORDER = {"properties": "name", "tasks": "grp, code, id", "prospects": "updated_at DESC",
          "posts": "venue", "templates": "name"}


def _crud(table: str) -> None:
    path = f"/{table}"
    parent = _PARENT.get(table)

    @router.get(path, name=f"list_{table}")
    def list_(property_id: Optional[int] = None, conn=Depends(get_conn)):
        where = {parent: property_id} if parent and property_id is not None else {}
        return ps.list_rows(conn, table, where, _ORDER[table])

    @router.post(path, name=f"create_{table}")
    def create(data: Dict[str, Any] = Body(...), conn=Depends(get_conn)):
        _require(data, *_REQUIRED[table])
        _validate(table, data)
        return ps.insert(conn, table, data)

    @router.post(f"{path}/bulk", name=f"bulk_{table}")
    def bulk(rows: List[Dict[str, Any]] = Body(...), conn=Depends(get_conn)):
        for r in rows:
            _require(r, *_REQUIRED[table])
            _validate(table, r)
        return [ps.insert(conn, table, r) for r in rows]

    @router.get(f"{path}/{{row_id}}", name=f"get_{table}")
    def get_(row_id: int, conn=Depends(get_conn)):
        return _or_404(ps.get(conn, table, row_id))

    @router.patch(f"{path}/{{row_id}}", name=f"update_{table}")
    def update_(row_id: int, data: Dict[str, Any] = Body(...), conn=Depends(get_conn)):
        _or_404(ps.get(conn, table, row_id))
        _validate(table, data)
        return ps.update(conn, table, row_id, data)

    @router.delete(f"{path}/{{row_id}}", name=f"delete_{table}")
    def delete_(row_id: int, conn=Depends(get_conn)):
        if not ps.delete(conn, table, row_id):
            raise HTTPException(404, "not found")
        return {"status": "deleted"}


# Prospect detail (with its message thread) is registered before the generic
# routes so it wins over the plain GET.
@router.get("/prospects/{row_id}")
def get_prospect(row_id: int, conn=Depends(get_conn)):
    p = _or_404(ps.get(conn, "prospects", row_id))
    p["messages"] = ps.list_rows(conn, "messages", {"prospect_id": row_id}, "created_at, id")
    return p


for _t in ("properties", "tasks", "prospects", "posts", "templates"):
    _crud(_t)


# --- tenants ↔ properties ---------------------------------------------------------

@router.patch("/tenants/{tenant_id}/property")
def assign_tenant(tenant_id: int, data: Dict[str, Any] = Body(...), conn=Depends(get_conn)):
    pid = data.get("property_id")
    if pid is not None:
        _or_404(ps.get(conn, "properties", int(pid)))
    cur = conn.execute("UPDATE tenants SET property_id = ? WHERE id = ?", (pid, tenant_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "tenant not found")
    return {"status": "ok", "tenant_id": tenant_id, "property_id": pid}


# --- messages -----------------------------------------------------------------------

def _touch_prospect(conn, prospect_id: int, direction: str) -> None:
    p = ps.get(conn, "prospects", prospect_id)
    if p is None:
        return
    changes: Dict[str, Any] = {"last_contact_at": ps.now()}
    if direction == "out" and p["status"] == "to_contact":
        changes["status"] = "contacted"
    if direction == "in" and p["status"] in ("to_contact", "contacted"):
        changes["status"] = "replied"
    ps.update(conn, "prospects", prospect_id, changes)


@router.post("/prospects/{prospect_id}/messages")
def add_message(prospect_id: int, data: Dict[str, Any] = Body(...), conn=Depends(get_conn)):
    """Add a draft (direction=out) or log a reply you received (direction=in)."""
    p = _or_404(ps.get(conn, "prospects", prospect_id))
    _require(data, "body")
    direction = data.get("direction", "out")
    _check(direction, ["out", "in"], "direction")
    row = {
        "prospect_id": prospect_id,
        "direction": direction,
        "channel": data.get("channel") or p["channel"],
        "subject": data.get("subject", ""),
        "body": data["body"],
        "status": "received" if direction == "in" else "draft",
        "sent_at": ps.now() if direction == "in" else "",
    }
    msg = ps.insert(conn, "messages", row)
    if direction == "in":
        _touch_prospect(conn, prospect_id, "in")
    return msg


@router.post("/prospects/{prospect_id}/draft")
def draft_from_template(prospect_id: int, data: Dict[str, Any] = Body(...),
                        conn=Depends(get_conn)):
    """Fill a template for one prospect and save it as a draft message."""
    p = _or_404(ps.get(conn, "prospects", prospect_id))
    t = _or_404(ps.get(conn, "templates", int(data.get("template_id", 0))))
    prop = ps.get(conn, "properties", p["property_id"])
    values = ps.placeholder_values(p, prop)
    return ps.insert(conn, "messages", {
        "prospect_id": prospect_id,
        "direction": "out",
        # The lead's channel wins: the same spiel goes out by DM or email.
        "channel": p["channel"],
        "subject": ps.render_template(t["subject"], values),
        "body": ps.render_template(t["body"], values).strip(),
        "status": "draft",
    })


@router.patch("/messages/{message_id}")
def edit_message(message_id: int, data: Dict[str, Any] = Body(...), conn=Depends(get_conn)):
    m = _or_404(ps.get(conn, "messages", message_id))
    if m["status"] != "draft":
        raise HTTPException(409, "only drafts can be edited")
    allowed = {k: data[k] for k in ("subject", "body", "channel") if k in data}
    return ps.update(conn, "messages", message_id, allowed)


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, conn=Depends(get_conn)):
    if not ps.delete(conn, "messages", message_id):
        raise HTTPException(404, "not found")
    return {"status": "deleted"}


@router.post("/messages/{message_id}/send")
async def send_message(message_id: int, request: Request, conn=Depends(get_conn)):
    """Approve a draft.

    Email with an address on file: sent over SMTP, marked sent only after the
    server accepts it. Any other channel: marked sent, because you posted it
    yourself (the app never touches Facebook).
    """
    m = _or_404(ps.get(conn, "messages", message_id))
    if m["status"] != "draft":
        raise HTTPException(409, f"message is already {m['status']}")
    p = _or_404(ps.get(conn, "prospects", m["prospect_id"]))
    emailed = False
    if m["channel"] == "email":
        if "@" not in p["contact"]:
            raise HTTPException(422, "prospect has no email address in 'contact'")
        if not m["subject"]:
            raise HTTPException(422, "email drafts need a subject")
        mailer = request.app.state.processor.mailer
        try:
            await asyncio.to_thread(mailer.send_notice, p["contact"], m["subject"], m["body"])
        except Exception as exc:
            raise HTTPException(502, f"SMTP send failed: {exc}")
        emailed = True
    ps.update(conn, "messages", message_id, {"status": "sent", "sent_at": ps.now()})
    _touch_prospect(conn, p["id"], "out")
    return {"status": "sent", "emailed": emailed, "message": ps.get(conn, "messages", message_id)}
