"""Local SQLite store: tenants, payments, and per-tenant invoice numbering.

Single-writer, low-volume (a handful of tenants, one payment each per month),
so a plain synchronous sqlite3 connection is more than enough. The reference
number is the idempotency key: a UNIQUE constraint makes reprocessing a safe
no-op.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from app.pipeline.parser import normalize_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name    TEXT NOT NULL,           -- shown on the receipt, e.g. "Rick Hilsendeger"
    match_name      TEXT NOT NULL UNIQUE,    -- normalized sender name for lookup
    monthly_rent    REAL NOT NULL,
    parking_fee     REAL NOT NULL DEFAULT 0,
    phone           TEXT DEFAULT '',
    email           TEXT DEFAULT '',         -- where the receipt PDF is sent
    last_invoice_no INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_number TEXT NOT NULL UNIQUE,    -- idempotency key from the email
    tenant_id        INTEGER REFERENCES tenants(id),
    sender_name      TEXT NOT NULL,
    amount           REAL NOT NULL,
    period           TEXT NOT NULL,
    payment_date     TEXT NOT NULL,           -- ISO date
    invoice_no       INTEGER,
    receipt_path     TEXT,
    emailed          INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);
"""


@dataclass
class Tenant:
    id: int
    display_name: str
    match_name: str
    monthly_rent: float
    parking_fee: float
    phone: str
    email: str
    last_invoice_no: int

    @property
    def expected_amount(self) -> float:
        return self.monthly_rent + self.parking_fee


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        # WAL + synchronous=NORMAL: crash-safe writes without fsync on every
        # statement. WAL persists at the DB level once set.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def backup_to(self, dest_path: str) -> str:
        """Write a consistent online copy of the DB (safe while in use)."""
        parent = os.path.dirname(dest_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        dest = sqlite3.connect(dest_path)
        try:
            with dest:
                self.conn.backup(dest)
        finally:
            dest.close()
        return dest_path

    def recover_failures(self) -> int:
        """Un-block payments that failed only because the tenant wasn't seeded yet.

        Deletes 'no tenant' failure rows whose sender now matches a tenant, so the
        next poll reprocesses them. Amount-mismatch failures are left in place
        (they need a human). Returns the number recovered.
        """
        rows = self.conn.execute(
            "SELECT id, sender_name FROM payments "
            "WHERE tenant_id IS NULL AND period LIKE 'FAILED: No tenant matches%'"
        ).fetchall()
        recovered = 0
        for r in rows:
            if self.get_tenant_by_name(r["sender_name"]):
                self.conn.execute("DELETE FROM payments WHERE id = ?", (r["id"],))
                recovered += 1
        if recovered:
            self.conn.commit()
        return recovered

    # --- tenants ---------------------------------------------------------
    def upsert_tenant(
        self,
        display_name: str,
        monthly_rent: float,
        parking_fee: float = 0.0,
        phone: str = "",
        email: str = "",
        last_invoice_no: int = 0,
        match_name: Optional[str] = None,
    ) -> None:
        key = normalize_name(match_name or display_name)
        self.conn.execute(
            """
            INSERT INTO tenants
                (display_name, match_name, monthly_rent, parking_fee, phone, email, last_invoice_no)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_name) DO UPDATE SET
                display_name    = excluded.display_name,
                monthly_rent    = excluded.monthly_rent,
                parking_fee     = excluded.parking_fee,
                phone           = excluded.phone,
                email           = excluded.email,
                -- Never move the invoice counter backwards: the seed value is a
                -- floor, runtime bumps (and manual corrections upward) win.
                last_invoice_no = max(last_invoice_no, excluded.last_invoice_no)
            """,
            (display_name, key, monthly_rent, parking_fee, phone, email, last_invoice_no),
        )
        self.conn.commit()

    def get_tenant_by_name(self, sender_name: str) -> Optional[Tenant]:
        key = normalize_name(sender_name)
        row = self.conn.execute(
            "SELECT * FROM tenants WHERE match_name = ?", (key,)
        ).fetchone()
        return self._row_to_tenant(row) if row else None

    @staticmethod
    def _row_to_tenant(row: sqlite3.Row) -> Tenant:
        return Tenant(
            id=row["id"],
            display_name=row["display_name"],
            match_name=row["match_name"],
            monthly_rent=row["monthly_rent"],
            parking_fee=row["parking_fee"],
            phone=row["phone"],
            email=row["email"],
            last_invoice_no=row["last_invoice_no"],
        )

    # --- payments --------------------------------------------------------
    def payment_exists(self, reference_number: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM payments WHERE reference_number = ?", (reference_number,)
        ).fetchone()
        return row is not None

    def record_payment(
        self,
        reference_number: str,
        tenant_id: int,
        sender_name: str,
        amount: float,
        period: str,
        payment_date: date,
        invoice_no: int,
        receipt_path: str = "",
        emailed: bool = False,
    ) -> int:
        """Insert the payment and bump the tenant's invoice counter atomically.

        The tenant counter is only advanced inside this single transaction, so a
        failed insert (e.g. duplicate reference number) never burns a number.
        """
        cur = self.conn.execute(
            """
            INSERT INTO payments
                (reference_number, tenant_id, sender_name, amount, period,
                 payment_date, invoice_no, receipt_path, emailed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_number,
                tenant_id,
                sender_name,
                amount,
                period,
                payment_date.isoformat(),
                invoice_no,
                receipt_path,
                1 if emailed else 0,
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.execute(
            "UPDATE tenants SET last_invoice_no = ? WHERE id = ?",
            (invoice_no, tenant_id),
        )
        self.conn.commit()
        return cur.lastrowid

    def record_failed(
        self,
        reference_number: str,
        sender_name: str,
        amount: float,
        reason: str,
    ) -> int:
        """Record a validation failure so a permanently-bad email is not retried.

        Uses the same UNIQUE reference number as the dedup key; tenant_id and
        invoice_no are left NULL so no invoice number is consumed.
        """
        cur = self.conn.execute(
            """
            INSERT INTO payments
                (reference_number, tenant_id, sender_name, amount, period,
                 payment_date, invoice_no, receipt_path, emailed, created_at)
            VALUES (?, NULL, ?, ?, ?, ?, NULL, ?, 0, ?)
            """,
            (
                reference_number,
                sender_name,
                amount,
                f"FAILED: {reason}",
                date.today().isoformat(),
                "",
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def mark_emailed(self, payment_id: int, receipt_path: str) -> None:
        self.conn.execute(
            "UPDATE payments SET emailed = 1, receipt_path = ? WHERE id = ?",
            (receipt_path, payment_id),
        )
        self.conn.commit()


def seed_from_json(store: Store, path: str) -> int:
    """Load/refresh tenants from a JSON seed file. Returns count loaded."""
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for t in data:
        store.upsert_tenant(
            display_name=t["display_name"],
            monthly_rent=float(t["monthly_rent"]),
            parking_fee=float(t.get("parking_fee", 0) or 0),
            phone=t.get("phone", ""),
            email=t.get("email", ""),
            last_invoice_no=int(t.get("last_invoice_no", 0)),
            match_name=t.get("match_name"),
        )
    return len(data)
