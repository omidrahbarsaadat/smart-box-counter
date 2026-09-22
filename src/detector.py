from __future__ import annotations

from abc import ABC, abstractmethod

import cv2
import numpy as np

from .models import Detection


class Detector(ABC):
    @abstractmethod
    def detect(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[list[Detection], np.ndarray | None]:
        raise NotImplementedError


class BackgroundBoxDetector(Detector):
    """Fast motion detector tuned for a fixed camera and mostly stable background."""

    def __init__(self, config: dict):
        self.config = config
        self.frame_number = 0
        self.subtractor = cv2.createBackgroundSubtractorMOG2(
            history=int(config["history"]),
            varThreshold=float(config["variance_threshold"]),
            detectShadows=bool(config.get("detect_shadows", True)),
        )
        blur_size = max(1, int(config.get("blur_kernel", 5))) | 1
        morph_size = max(1, int(config.get("morph_kernel", 7))) | 1
        self.blur_size = blur_size
        self.kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (morph_size, morph_size))

    def detect(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> tuple[list[Detection], np.ndarray]:
        self.frame_number += 1
        rx, ry, rw, rh = roi
        roi_frame = frame[ry : ry + rh, rx : rx + rw]
        gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (self.blur_size, self.blur_size), 0)
        mask = self.subtractor.apply(gray, learningRate=float(self.config.get("learning_rate", -1)))
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)
        mask = cv2.dilate(mask, self.kernel, iterations=1)

        if self.frame_number <= int(self.config.get("warmup_frames", 15)):
            return [], mask

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[Detection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            x, y, w, h = cv2.boundingRect(contour)
            rect_area = max(1, w * h)
            aspect = w / max(1, h)
            rectangularity = area / rect_area
            if not (self.config["min_area"] <= area <= self.config["max_area"]):
                continue
            if w < self.config["min_width"] or h < self.config["min_height"]:
                continue
            if not (self.config["min_aspect_ratio"] <= aspect <= self.config["max_aspect_ratio"]):
                continue
            if rectangularity < self.config["min_rectangularity"]:
                continue
            confidence = min(1.0, 0.5 * rectangularity + 0.5 * min(1.0, area / (self.config["min_area"] * 3)))
            detections.append(Detection((x + rx, y + ry, w, h), confidence))
        return detections, mask
