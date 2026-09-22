from __future__ import annotations

import csv
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


class EventStore:
    def __init__(self, database_path: str | Path, snapshots_dir: str | Path, save_snapshots: bool = True):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir = Path(snapshots_dir)
        self.save_snapshots = save_snapshots
        self.session_id = uuid.uuid4().hex
        if self.save_snapshots:
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        existing_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(box_events)").fetchall()
        }
        migrated_legacy = bool(existing_columns and "session_id" not in existing_columns)
        if migrated_legacy:
            # Preserve databases made by MVP builds before per-run session IDs existed.
            self.connection.execute("ALTER TABLE box_events RENAME TO box_events_legacy")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS box_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                color TEXT NOT NULL,
                confidence REAL NOT NULL,
                camera_id TEXT NOT NULL,
                snapshot_path TEXT,
                UNIQUE(session_id, camera_id, track_id)
            )
            """
        )
        if migrated_legacy:
            self.connection.execute(
                """
                INSERT INTO box_events(session_id, timestamp, track_id, color, confidence, camera_id, snapshot_path)
                SELECT 'legacy', timestamp, track_id, color, confidence, camera_id, snapshot_path
                FROM box_events_legacy
                """
            )
        self.connection.commit()

    def record(self, track_id: int, color: str, confidence: float, camera_id: str, crop: np.ndarray | None) -> bool:
        timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
        snapshot_path = None
        if self.save_snapshots and crop is not None and crop.size:
            safe_timestamp = timestamp.replace(":", "-")
            target = self.snapshots_dir / f"{safe_timestamp}_cam-{camera_id}_track-{track_id}_{color}.jpg"
            if cv2.imwrite(str(target), crop):
                snapshot_path = str(target)
        try:
            self.connection.execute(
                "INSERT INTO box_events(session_id, timestamp, track_id, color, confidence, camera_id, snapshot_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.session_id, timestamp, int(track_id), color, float(confidence), str(camera_id), snapshot_path),
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            if snapshot_path:
                Path(snapshot_path).unlink(missing_ok=True)
            return False

    def counts_by_color(self) -> dict[str, int]:
        rows = self.connection.execute("SELECT color, COUNT(*) FROM box_events GROUP BY color").fetchall()
        return {str(color): int(count) for color, count in rows}

    def total(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM box_events").fetchone()[0])

    def export_csv(self, target: str | Path) -> Path:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.connection.execute(
            "SELECT timestamp, track_id, color, confidence, camera_id, snapshot_path FROM box_events ORDER BY id"
        ).fetchall()
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("timestamp", "track_id", "color", "confidence", "camera_id", "snapshot_path"))
            writer.writerows(rows)
        return target

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
