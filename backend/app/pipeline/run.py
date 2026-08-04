"""CLI entrypoint for the receipt pipeline.

Usage (run from backend/, so `app.*` imports resolve):

    python -m app.pipeline.run seed          # load/refresh tenants from JSON
    python -m app.pipeline.run prep          # render + record receipts, do NOT email
    python -m app.pipeline.run send          # email prepped-but-unsent receipts
    python -m app.pipeline.run poll          # prep + send in one shot (auto)
    python -m app.pipeline.run tenants       # list tenants + their invoice counter
    python -m app.pipeline.run backup        # write a timestamped DB backup now
"""

from __future__ import annotations

import json
import sys

from app.config import get_settings
from app.pipeline.processor import PaymentProcessor
from app.pipeline.store import Store, seed_from_json


def cmd_seed() -> int:
    settings = get_settings()
    store = Store(settings.db_path)
    try:
        n = seed_from_json(store, settings.tenants_seed_path)
    finally:
        store.close()
    print(f"Seeded/updated {n} tenants from {settings.tenants_seed_path}")
    return 0


def cmd_tenants() -> int:
    settings = get_settings()
    store = Store(settings.db_path)
    try:
        rows = store.conn.execute(
            "SELECT display_name, monthly_rent, parking_fee, last_invoice_no, email "
            "FROM tenants ORDER BY display_name"
        ).fetchall()
    finally:
        store.close()
    if not rows:
        print("No tenants. Run 'seed' first.")
        return 0
    for r in rows:
        print(
            f"{r['display_name']:<22} rent={r['monthly_rent']:<7} "
            f"parking={r['parking_fee']:<5} last_invoice#={r['last_invoice_no']:<4} "
            f"email={r['email'] or '-'}"
        )
    return 0


def cmd_prep() -> int:
    settings = get_settings()
    processor = PaymentProcessor(settings)
    summary = processor.process_new_payments(send_email=False)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_send() -> int:
    settings = get_settings()
    processor = PaymentProcessor(settings)
    summary = processor.send_pending_receipts()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_poll() -> int:
    settings = get_settings()
    processor = PaymentProcessor(settings)
    summary = processor.process_new_payments(send_email=True)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_backup() -> int:
    from app.pipeline.backup import run_backup

    settings = get_settings()
    store = Store(settings.db_path)
    try:
        path = run_backup(store, settings.backup_dir, settings.backup_retention)
    finally:
        store.close()
    print("backup ->", path)
    return 0


COMMANDS = {
    "seed": cmd_seed,
    "prep": cmd_prep,
    "send": cmd_send,
    "poll": cmd_poll,
    "tenants": cmd_tenants,
    "backup": cmd_backup,
}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: python -m app.pipeline.run [{'|'.join(COMMANDS)}]")
        return 2
    return COMMANDS[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main())
