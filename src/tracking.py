from __future__ import annotations

import math

from .models import Detection, Track


class CentroidTracker:
    """Small dependency-free tracker with one-to-one greedy assignment."""

    def __init__(self, max_distance: float = 100, max_missed_frames: int = 10):
        self.max_distance = float(max_distance)
        self.max_missed_frames = int(max_missed_frames)
        self.tracks: dict[int, Track] = {}
        self.next_id = 1

    def _register(self, detection: Detection) -> Track:
        track = Track(self.next_id, detection.bbox, detection.centroid, detection_confidence=detection.confidence)
        self.tracks[self.next_id] = track
        self.next_id += 1
        return track

    def update(self, detections: list[Detection]) -> list[Track]:
        if not self.tracks:
            return [self._register(d) for d in detections]

        for track in self.tracks.values():
            track.missed_frames += 1

        candidates: list[tuple[float, int, int]] = []
        for track_id, track in self.tracks.items():
            for detection_index, detection in enumerate(detections):
                distance = math.dist(track.centroid, detection.centroid)
                if distance <= self.max_distance:
                    candidates.append((distance, track_id, detection_index))

        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        visible: list[Track] = []
        for _, track_id, detection_index in sorted(candidates):
            if track_id in assigned_tracks or detection_index in assigned_detections:
                continue
            track = self.tracks[track_id]
            track.update(detections[detection_index])
            assigned_tracks.add(track_id)
            assigned_detections.add(detection_index)
            visible.append(track)

        for index, detection in enumerate(detections):
            if index not in assigned_detections:
                visible.append(self._register(detection))

        expired = [track_id for track_id, track in self.tracks.items() if track.missed_frames > self.max_missed_frames]
        for track_id in expired:
            del self.tracks[track_id]
        return visible


class ExternalIdTracker:
    """Maintains count state for IDs supplied by Ultralytics ByteTrack."""

    def __init__(self, max_missed_frames: int = 30):
        self.max_missed_frames = max_missed_frames
        self.tracks: dict[int, Track] = {}

    def update(self, detections: list[Detection]) -> list[Track]:
        for track in self.tracks.values():
            track.missed_frames += 1
        visible = []
        for detection in detections:
            if detection.track_id is None:
                continue
            track_id = int(detection.track_id)
            if track_id in self.tracks:
                self.tracks[track_id].update(detection)
            else:
                self.tracks[track_id] = Track(
                    track_id, detection.bbox, detection.centroid, detection_confidence=detection.confidence
                )
            visible.append(self.tracks[track_id])
        expired = [key for key, value in self.tracks.items() if value.missed_frames > self.max_missed_frames]
        for key in expired:
            del self.tracks[key]
        return visible
