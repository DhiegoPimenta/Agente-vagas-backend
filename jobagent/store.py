from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Scored

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  uid TEXT PRIMARY KEY,
  source TEXT, title TEXT, company TEXT, location TEXT, url TEXT,
  score INTEGER, route TEXT, flags TEXT,
  first_seen TEXT, last_seen TEXT, emailed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, collected INTEGER, new INTEGER, recommended INTEGER, discarded INTEGER
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def known(self, uids) -> set[str]:
        uids = list(uids)
        out: set[str] = set()
        for i in range(0, len(uids), 500):
            chunk = uids[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT uid FROM jobs WHERE uid IN ({placeholders})", chunk
            )
            out |= {r[0] for r in rows}
        return out

    def upsert(self, scored: Scored) -> None:
        job = scored.job
        now = _now()
        self.conn.execute(
            """
            INSERT INTO jobs (uid, source, title, company, location, url, score, route, flags, first_seen, last_seen, emailed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(uid) DO UPDATE SET
              last_seen = excluded.last_seen,
              score = excluded.score,
              route = excluded.route,
              flags = excluded.flags
            """,
            (
                job.uid, job.source, job.title, job.company, job.location, job.url,
                scored.score, scored.route, ",".join(scored.flags), now, now,
            ),
        )

    def mark_emailed(self, uids) -> None:
        self.conn.executemany("UPDATE jobs SET emailed = 1 WHERE uid = ?", [(u,) for u in uids])

    def record_run(self, collected: int, new: int, recommended: int, discarded: int) -> None:
        self.conn.execute(
            "INSERT INTO runs (started_at, collected, new, recommended, discarded) VALUES (?, ?, ?, ?, ?)",
            (_now(), collected, new, recommended, discarded),
        )

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
