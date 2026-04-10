"""SQLite repository for alert state."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from alert.models import AlertItem, StoredAlert


class AlertRepository:
    """Persisted storage for sent alerts."""

    def __init__(self, db_file: str) -> None:
        db_path = Path(db_file)
        if db_path.parent != Path():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path)
        self._connection.row_factory = sqlite3.Row
        self.ensure_schema()

    def ensure_schema(self) -> None:
        cursor = self._connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                target_url TEXT NOT NULL,
                item_id TEXT NOT NULL,
                message TEXT NOT NULL,
                value TEXT,
                occurred_at TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS alerts_source_target_item
            ON alerts(source_name, target_url, item_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS alerts_lookup
            ON alerts(source_name, target_url, created_at DESC, id DESC)
            """
        )
        self._connection.commit()

    def get_history(self, source_name: str, target_url: str) -> list[StoredAlert]:
        cursor = self._connection.cursor()
        cursor.execute(
            """
            SELECT source_name, target_url, item_id, message, value, occurred_at, metadata_json, created_at
            FROM alerts
            WHERE source_name = ? AND target_url = ?
            ORDER BY created_at DESC, id DESC
            """,
            (source_name, target_url),
        )
        rows = cursor.fetchall()
        return [
            StoredAlert(
                source_name=row["source_name"],
                target_url=row["target_url"],
                item_id=row["item_id"],
                message=row["message"],
                value=row["value"],
                occurred_at=row["occurred_at"],
                metadata=json.loads(row["metadata_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_alerts(self, source_name: str, target_url: str, alerts: list[AlertItem]) -> int:
        if not alerts:
            return 0

        created_at = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                source_name,
                target_url,
                alert.item_id,
                alert.message,
                alert.value,
                alert.occurred_at,
                json.dumps(dict(alert.metadata), sort_keys=True),
                created_at,
            )
            for alert in alerts
        ]

        cursor = self._connection.cursor()
        cursor.executemany(
            """
            INSERT OR IGNORE INTO alerts (
                source_name,
                target_url,
                item_id,
                message,
                value,
                occurred_at,
                metadata_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._connection.commit()
        return cursor.rowcount

    def prune(self, source_name: str, target_url: str, keep: int = 1000) -> int:
        if keep < 0:
            raise ValueError("keep must be non-negative")
        cursor = self._connection.cursor()
        cursor.execute(
            """
            DELETE FROM alerts
            WHERE id IN (
                SELECT id
                FROM alerts
                WHERE source_name = ? AND target_url = ?
                ORDER BY created_at DESC, id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (source_name, target_url, keep),
        )
        self._connection.commit()
        return cursor.rowcount

    def close(self) -> None:
        self._connection.close()
