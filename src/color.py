from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np

from .models import BBox


class HSVColorClassifier:
    def __init__(self, config: dict):
        self.ranges = config["ranges"]
        self.inner_crop_ratio = float(config.get("inner_crop_ratio", 0.15))
        self.min_coverage = float(config.get("min_coverage", 0.08))

    def classify(self, frame: np.ndarray, bbox: BBox) -> tuple[str, float]:
        frame_h, frame_w = frame.shape[:2]
        x, y, w, h = bbox
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(frame_w, x + w), min(frame_h, y + h)
        if x2 <= x1 or y2 <= y1:
            return "unknown", 0.0
        crop = frame[y1:y2, x1:x2]
        inset_x = int(crop.shape[1] * self.inner_crop_ratio)
        inset_y = int(crop.shape[0] * self.inner_crop_ratio)
        if crop.shape[1] > inset_x * 2 + 2 and crop.shape[0] > inset_y * 2 + 2:
            crop = crop[inset_y : crop.shape[0] - inset_y, inset_x : crop.shape[1] - inset_x]
        if crop.size == 0:
            return "unknown", 0.0

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        pixel_count = float(hsv.shape[0] * hsv.shape[1])
        scores: dict[str, float] = defaultdict(float)
        for color_name, color_ranges in self.ranges.items():
            combined = np.zeros(hsv.shape[:2], dtype=np.uint8)
            for range_config in color_ranges:
                lower = np.array(range_config["lower"], dtype=np.uint8)
                upper = np.array(range_config["upper"], dtype=np.uint8)
                combined = cv2.bitwise_or(combined, cv2.inRange(hsv, lower, upper))
            scores[color_name.lower()] = cv2.countNonZero(combined) / pixel_count
        if not scores:
            return "unknown", 0.0
        color, coverage = max(scores.items(), key=lambda item: item[1])
        return (color, float(coverage)) if coverage >= self.min_coverage else ("unknown", float(coverage))
