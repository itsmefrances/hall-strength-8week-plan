"""SQLite state (dedup + history) and a JSONL event log."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    url           TEXT PRIMARY KEY,
    title         TEXT,
    status        TEXT NOT NULL,          -- seeded | posted | pending | error
    ig_post_id    TEXT,
    ig_permalink  TEXT,
    image_url     TEXT,
    error         TEXT,
    discovered_at TEXT NOT NULL,
    posted_at     TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: Path, log_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(SCHEMA)
        self.conn.commit()
        self.log_path = log_path

    def close(self) -> None:
        self.conn.close()

    def is_empty(self) -> bool:
        (count,) = self.conn.execute("SELECT COUNT(*) FROM processed").fetchone()
        return count == 0

    def is_processed(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM processed WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def mark(
        self,
        url: str,
        status: str,
        title: str = "",
        ig_post_id: str = "",
        ig_permalink: str = "",
        image_url: str = "",
        error: str = "",
    ) -> None:
        posted_at = _now() if status == "posted" else None
        self.conn.execute(
            """
            INSERT INTO processed
                (url, title, status, ig_post_id, ig_permalink, image_url, error,
                 discovered_at, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                status = excluded.status,
                ig_post_id = excluded.ig_post_id,
                ig_permalink = excluded.ig_permalink,
                image_url = excluded.image_url,
                error = excluded.error,
                posted_at = COALESCE(excluded.posted_at, processed.posted_at)
            """,
            (url, title, status, ig_post_id, ig_permalink, image_url, error,
             _now(), posted_at),
        )
        self.conn.commit()
        self.log_event(status, url=url, title=title, ig_post_id=ig_post_id,
                       error=error)

    def log_event(self, event: str, **fields) -> None:
        record = {"ts": _now(), "event": event}
        record.update({k: v for k, v in fields.items() if v})
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
