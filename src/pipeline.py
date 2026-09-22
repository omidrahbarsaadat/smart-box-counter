from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from time import perf_counter

import cv2
import numpy as np

from .color import HSVColorClassifier
from .config import resolve_path
from .detector import BackgroundBoxDetector, Detector
from .models import Track
from .storage import EventStore
from .tracking import CentroidTracker, ExternalIdTracker
from .yolo_detector import YOLOByteTrackDetector


PALETTE = {
    "red": (0, 0, 255),
    "blue": (255, 80, 20),
    "green": (0, 200, 0),
    "yellow": (0, 230, 255),
    "white": (245, 245, 245),
    "black": (40, 40, 40),
    "brown": (30, 90, 150),
    "unknown": (160, 160, 160),
}


@dataclass
class FrameResult:
    frame: np.ndarray
    mask: np.ndarray | None
    counted_track_ids: list[int]
    total: int
    counts_by_color: dict[str, int]


class BoxCounterPipeline:
    def __init__(self, config: dict, detector_name: str = "classical"):
        self.config = config
        self.detector_name = detector_name
        self.detector: Detector
        if detector_name == "yolo":
            self.detector = YOLOByteTrackDetector(config["yolo"])
            self.tracker = ExternalIdTracker(config["tracking"]["max_missed_frames"])
        else:
            self.detector = BackgroundBoxDetector(config["detection"])
            self.tracker = CentroidTracker(
                config["tracking"]["max_distance"], config["tracking"]["max_missed_frames"]
            )
        self.classifier = HSVColorClassifier(config["color_detection"])
        storage = config["storage"]
        self.store = EventStore(
            resolve_path(config, storage["database"]),
            resolve_path(config, storage["snapshots_dir"]),
            bool(storage.get("save_snapshots", True)),
        )
        self.camera_id = str(config["camera"].get("id", 0))
        self._last_tick = perf_counter()
        self._fps = 0.0

    @staticmethod
    def get_roi(frame: np.ndarray, roi_config: dict) -> tuple[int, int, int, int]:
        height, width = frame.shape[:2]
        x = max(0, min(width - 1, round(width * float(roi_config["x"]))))
        y = max(0, min(height - 1, round(height * float(roi_config["y"]))))
        w = max(1, min(width - x, round(width * float(roi_config["width"]))))
        h = max(1, min(height - y, round(height * float(roi_config["height"]))))
        return x, y, w, h

    def _line_y(self, roi: tuple[int, int, int, int]) -> int:
        return roi[1] + round(roi[3] * float(self.config["counting_line"]["position"]))

    def _update_side_and_check_crossing(self, track: Track, line_y: int) -> bool:
        cfg = self.config["counting_line"]
        hysteresis = int(cfg.get("hysteresis_px", 5))
        offset = track.centroid[1] - line_y
        current_side = -1 if offset < -hysteresis else 1 if offset > hysteresis else 0
        crossed = False
        if current_side and track.stable_side and current_side != track.stable_side:
            direction = cfg.get("direction", "any")
            moving_down = track.stable_side == -1 and current_side == 1
            direction_ok = direction == "any" or (direction == "down" and moving_down) or (direction == "up" and not moving_down)
            frame_movement = 0.0
            if track.previous_centroid is not None:
                frame_movement = abs(track.centroid[1] - track.previous_centroid[1])
            tracking_cfg = self.config["tracking"]
            mature = track.observed_frames >= int(tracking_cfg["min_confirmed_frames"])
            moved = track.total_movement >= float(tracking_cfg["min_total_movement_px"])
            crossing_motion = frame_movement >= float(cfg.get("min_crossing_movement_px", 2))
            crossed = direction_ok and mature and moved and crossing_motion and not track.counted
        if current_side:
            track.stable_side = current_side
        return crossed

    @staticmethod
    def _safe_crop(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray | None:
        x, y, w, h = bbox
        frame_h, frame_w = frame.shape[:2]
        x1, y1, x2, y2 = max(0, x), max(0, y), min(frame_w, x + w), min(frame_h, y + h)
        return frame[y1:y2, x1:x2].copy() if x2 > x1 and y2 > y1 else None

    @staticmethod
    def _best_color(track: Track) -> tuple[str, float]:
        if not track.color_votes:
            return "unknown", 0.0
        grouped: dict[str, list[float]] = {}
        for name, confidence in track.color_votes:
            grouped.setdefault(name, []).append(confidence)
        color = max(grouped, key=lambda key: (len(grouped[key]), sum(grouped[key])))
        return color, sum(grouped[color]) / len(grouped[color])

    def process(self, frame: np.ndarray) -> FrameResult:
        roi = self.get_roi(frame, self.config["roi"])
        detections, mask = self.detector.detect(frame, roi)
        tracks = self.tracker.update(detections)
        line_y = self._line_y(roi)
        counted_ids: list[int] = []

        for track in tracks:
            color, color_confidence = self.classifier.classify(frame, track.bbox)
            track.color_votes.append((color, color_confidence))
            track.color_votes = track.color_votes[-12:]
            if self._update_side_and_check_crossing(track, line_y):
                best_color, best_confidence = self._best_color(track)
                confidence = max(0.0, min(1.0, best_confidence * track.detection_confidence))
                inserted = self.store.record(
                    track.track_id,
                    best_color,
                    confidence,
                    self.camera_id,
                    self._safe_crop(frame, track.bbox),
                )
                track.counted = True
                if inserted:
                    counted_ids.append(track.track_id)

        now = perf_counter()
        instantaneous = 1.0 / max(1e-9, now - self._last_tick)
        self._fps = instantaneous if self._fps == 0 else self._fps * 0.9 + instantaneous * 0.1
        self._last_tick = now
        counts = self.store.counts_by_color()
        total = sum(counts.values())
        annotated = self._draw(frame.copy(), tracks, roi, line_y, total, counts)
        return FrameResult(annotated, mask, counted_ids, total, counts)

    def _draw(self, frame: np.ndarray, tracks: list[Track], roi, line_y, total, counts) -> np.ndarray:
        rx, ry, rw, rh = roi
        cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), (90, 90, 90), 1)
        cv2.line(frame, (rx, line_y), (rx + rw, line_y), (0, 165, 255), 3)
        cv2.putText(frame, "COUNT LINE", (rx + 8, max(20, line_y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2)
        for track in tracks:
            color, confidence = self._best_color(track)
            x, y, w, h = track.bbox
            draw_color = PALETTE.get(color, PALETTE["unknown"])
            cv2.rectangle(frame, (x, y), (x + w, y + h), draw_color, 2)
            label = f"ID {track.track_id} | {color} {confidence:.0%}"
            cv2.putText(frame, label, (x, max(18, y - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.52, draw_color, 2)
        panel_lines = [f"Total: {total}", f"FPS: {self._fps:.1f}"]
        color_order = ("red", "blue", "green", "yellow", "white", "black", "brown", "unknown")
        panel_lines.extend(f"{name.title()}: {counts.get(name, 0)}" for name in color_order)
        panel_width, line_height = 185, 22
        overlay = frame.copy()
        cv2.rectangle(overlay, (8, 8), (8 + panel_width, 20 + line_height * len(panel_lines)), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
        for index, text in enumerate(panel_lines):
            cv2.putText(frame, text, (18, 30 + index * line_height), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (245, 245, 245), 1, cv2.LINE_AA)
        return frame

    def export_csv(self) -> str:
        target = resolve_path(self.config, self.config["storage"]["csv_export"])
        return str(self.store.export_csv(target))

    def close(self) -> None:
        self.store.close()
