from pathlib import Path

import numpy as np

from src.storage import EventStore


def test_record_is_unique_per_camera_and_track(tmp_path: Path):
    with EventStore(tmp_path / "counts.db", tmp_path / "snapshots", save_snapshots=False) as store:
        crop = np.zeros((10, 10, 3), dtype=np.uint8)
        assert store.record(7, "red", 0.9, "cam-a", crop)
        assert not store.record(7, "red", 0.9, "cam-a", crop)
        assert store.record(7, "red", 0.9, "cam-b", crop)
        assert store.total() == 2
        csv_path = store.export_csv(tmp_path / "events.csv")
    assert csv_path.exists()
    assert "timestamp,track_id,color,confidence,camera_id,snapshot_path" in csv_path.read_text()


def test_track_ids_can_restart_in_a_new_session(tmp_path: Path):
    database = tmp_path / "counts.db"
    with EventStore(database, tmp_path / "snapshots", save_snapshots=False) as first:
        assert first.record(1, "blue", 0.8, "cam-a", None)
    with EventStore(database, tmp_path / "snapshots", save_snapshots=False) as second:
        assert second.record(1, "blue", 0.8, "cam-a", None)
        assert second.total() == 2
