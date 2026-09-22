from __future__ import annotations

import numpy as np

from .detector import Detector
from .models import Detection


class YOLOByteTrackDetector(Detector):
    """Optional YOLO26 detector using Ultralytics' built-in ByteTrack support."""

    def __init__(self, config: dict):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "YOLO mode is optional. Install it with: pip install -r requirements-yolo.txt"
            ) from exc
        self.model = YOLO(config.get("model", "yolo26n.pt"))
        self.confidence = float(config.get("confidence", 0.25))
        self.iou = float(config.get("iou", 0.7))
        self.device = config.get("device")
        self.classes = config.get("classes")

    def detect(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[list[Detection], None]:
        rx, ry, rw, rh = roi
        crop = frame[ry : ry + rh, rx : rx + rw]
        kwargs = {
            "persist": True,
            "tracker": "bytetrack.yaml",
            "conf": self.confidence,
            "iou": self.iou,
            "verbose": False,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        if self.classes is not None:
            kwargs["classes"] = self.classes
        results = self.model.track(crop, **kwargs)
        detections: list[Detection] = []
        if not results or results[0].boxes is None or results[0].boxes.id is None:
            return detections, None
        boxes = results[0].boxes
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        for coords, track_id, confidence in zip(xyxy, ids, confidences):
            x1, y1, x2, y2 = map(int, coords)
            detections.append(
                Detection((x1 + rx, y1 + ry, max(1, x2 - x1), max(1, y2 - y1)), float(confidence), int(track_id))
            )
        return detections, None
