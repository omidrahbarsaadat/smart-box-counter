from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a repeatable box-counting demo video.")
    parser.add_argument("--output", default="data/demo.mp4")
    parser.add_argument("--preview", default="docs/demo-preview.jpg")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    Path(args.preview).parent.mkdir(parents=True, exist_ok=True)

    width, height, fps, frames = 640, 480, 30, 210
    codec = "VP80" if output.suffix.lower() == ".webm" else "mp4v"
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not create demo video ({codec} codec unavailable)")

    preview_frame = None
    boxes = [
        {"start": 25, "x": 135, "color": (0, 0, 220), "label": "RED"},
        {"start": 95, "x": 365, "color": (220, 70, 20), "label": "BLUE"},
    ]
    for frame_index in range(frames):
        frame = np.full((height, width, 3), (205, 205, 205), dtype=np.uint8)
        cv2.rectangle(frame, (30, 20), (610, 460), (180, 180, 180), 4)
        cv2.line(frame, (30, 250), (610, 250), (0, 165, 255), 2)
        cv2.putText(frame, "SYNTHETIC CONVEYOR TEST", (165, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 60), 2)
        for box in boxes:
            age = frame_index - box["start"]
            if 0 <= age < 80:
                y = -75 + age * 7
                x = box["x"]
                cv2.rectangle(frame, (x, y), (x + 115, y + 80), box["color"], -1)
                cv2.rectangle(frame, (x, y), (x + 115, y + 80), (40, 40, 40), 3)
                cv2.putText(frame, box["label"], (x + 24, y + 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        writer.write(frame)
        if frame_index == 135:
            preview_frame = frame.copy()
    writer.release()
    if preview_frame is not None:
        cv2.imwrite(args.preview, preview_frame)
    print(f"Generated {output} ({frames} frames at {fps} FPS)")


if __name__ == "__main__":
    main()
