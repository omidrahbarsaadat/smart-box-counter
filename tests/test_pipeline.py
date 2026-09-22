from pathlib import Path

import numpy as np

from src.config import load_config
from src.models import Detection
from src.pipeline import BoxCounterPipeline


class SequenceDetector:
    def __init__(self, y_positions):
        self.positions = iter(y_positions)

    def detect(self, frame, roi):
        y = next(self.positions)
        return [Detection((120, y, 80, 60), 0.95)], None


def make_pipeline(tmp_path: Path, positions):
    config_path = Path(__file__).parents[1] / "config.yaml"
    config = load_config(config_path)
    config["storage"]["database"] = str(tmp_path / "events.db")
    config["storage"]["snapshots_dir"] = str(tmp_path / "snapshots")
    config["storage"]["csv_export"] = str(tmp_path / "events.csv")
    config["storage"]["save_snapshots"] = False
    config["roi"] = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}
    config["counting_line"]["position"] = 0.5
    config["tracking"]["min_confirmed_frames"] = 2
    config["tracking"]["min_total_movement_px"] = 10
    pipeline = BoxCounterPipeline(config)
    pipeline.detector = SequenceDetector(positions)
    return pipeline


def test_crossing_counts_once(tmp_path):
    pipeline = make_pipeline(tmp_path, [80, 120, 165, 205, 240, 260, 290, 330])
    frame = np.full((480, 640, 3), (0, 0, 220), dtype=np.uint8)
    events = []
    for _ in range(8):
        events.extend(pipeline.process(frame).counted_track_ids)
    assert len(events) == 1
    assert pipeline.store.total() == 1
    assert pipeline.store.counts_by_color() == {"red": 1}
    pipeline.close()


def test_stationary_object_is_not_counted(tmp_path):
    pipeline = make_pipeline(tmp_path, [180] * 8)
    frame = np.full((480, 640, 3), (0, 0, 220), dtype=np.uint8)
    for _ in range(8):
        pipeline.process(frame)
    assert pipeline.store.total() == 0
    pipeline.close()
