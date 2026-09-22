from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


BBox = tuple[int, int, int, int]
Point = tuple[int, int]


@dataclass(slots=True)
class Detection:
    bbox: BBox
    confidence: float = 1.0
    track_id: Optional[int] = None

    @property
    def centroid(self) -> Point:
        x, y, w, h = self.bbox
        return x + w // 2, y + h // 2


@dataclass
class Track:
    track_id: int
    bbox: BBox
    centroid: Point
    previous_centroid: Optional[Point] = None
    missed_frames: int = 0
    observed_frames: int = 1
    total_movement: float = 0.0
    counted: bool = False
    stable_side: int = 0
    color_votes: list[tuple[str, float]] = field(default_factory=list)
    detection_confidence: float = 1.0

    def update(self, detection: Detection) -> None:
        import math

        new_centroid = detection.centroid
        self.previous_centroid = self.centroid
        self.total_movement += math.dist(self.centroid, new_centroid)
        self.centroid = new_centroid
        self.bbox = detection.bbox
        self.detection_confidence = detection.confidence
        self.missed_frames = 0
        self.observed_frames += 1
