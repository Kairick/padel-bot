"""One SQLite connection for the whole process, shared by stats and subscriptions.

Handlers and the monitor run in one event loop and never `await` inside `with db:`,
so transactions don't interleave.
"""

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db
