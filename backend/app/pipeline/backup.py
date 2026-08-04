"""Timestamped SQLite backups with retention.

The DB is the sole source of truth for payment dedup and invoice numbering, so a
lost/corrupted file risks duplicate receipts and colliding invoice numbers. These
backups go to a durable, separate volume (e.g. the hermes ZFS share) mounted at
BACKUP_DIR.
"""

from __future__ import annotations

import glob
import os
from datetime import datetime

from app.pipeline.store import Store

_PREFIX = "mypropmate-"


def prune(backup_dir: str, retention: int) -> None:
    """Keep the newest `retention` backups; delete older ones."""
    if retention <= 0:
        return
    files = sorted(glob.glob(os.path.join(backup_dir, f"{_PREFIX}*.db")))
    for old in files[:-retention]:
        try:
            os.remove(old)
        except OSError:
            pass


def run_backup(store: Store, backup_dir: str, retention: int) -> str:
    """Write one timestamped backup and prune old ones. Returns the new path."""
    os.makedirs(backup_dir, exist_ok=True)
    # Microsecond suffix so two backups in the same second don't collide.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = os.path.join(backup_dir, f"{_PREFIX}{ts}.db")
    store.backup_to(dest)
    prune(backup_dir, retention)
    return dest
