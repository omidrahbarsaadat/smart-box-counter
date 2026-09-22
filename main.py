from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from src.calibration import run_calibration
from src.config import load_config
from src.pipeline import BoxCounterPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect, track, classify, count, and log moving boxes.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--camera", type=int, help="USB camera index, for example 0")
    source.add_argument("--video", type=str, help="Video file used as the input")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path")
    parser.add_argument("--detector", choices=("classical", "yolo"), default="classical")
    parser.add_argument("--model", help="YOLO26 model path; implies --detector yolo")
    parser.add_argument("--calibrate", action="store_true", help="Open interactive camera/video calibration")
    parser.add_argument("--headless", action="store_true", help="Process without opening display windows")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N frames (0 processes all)")
    parser.add_argument("--export-csv", action="store_true", help="Export the database to CSV and exit")
    parser.add_argument("--no-snapshots", action="store_true", help="Disable snapshots for this run")
    return parser


def open_capture(args, config) -> tuple[cv2.VideoCapture, str]:
    if args.video:
        video_path = Path(args.video).expanduser().resolve()
        capture = cv2.VideoCapture(str(video_path))
        source_name = str(video_path)
        config["camera"]["id"] = video_path.stem
    else:
        camera_id = args.camera if args.camera is not None else int(config["camera"].get("id", 0))
        capture = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(config["camera"].get("width", 1280)))
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(config["camera"].get("height", 720)))
        capture.set(cv2.CAP_PROP_FPS, int(config["camera"].get("fps", 30)))
        source_name = f"camera {camera_id}"
        config["camera"]["id"] = camera_id
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {source_name}. Check the camera index or video path.")
    return capture, source_name


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.model:
            config["yolo"]["model"] = args.model
            args.detector = "yolo"
        if args.no_snapshots:
            config["storage"]["save_snapshots"] = False

        if args.export_csv:
            pipeline = BoxCounterPipeline(config, args.detector)
            target = pipeline.export_csv()
            pipeline.close()
            print(f"CSV exported to {target}")
            return 0

        capture, source_name = open_capture(args, config)
        if args.calibrate:
            run_calibration(capture, config)
            capture.release()
            return 0

        pipeline = BoxCounterPipeline(config, args.detector)
        print(f"Processing {source_name} with {args.detector} detector. Press Q or Esc to stop.")
        frames = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                result = pipeline.process(frame)
                frames += 1
                for track_id in result.counted_track_ids:
                    print(f"Counted track {track_id}; total={result.total}; colors={result.counts_by_color}")
                if not args.headless:
                    scale = float(config.get("display", {}).get("scale", 1.0))
                    display_frame = result.frame
                    if scale != 1.0:
                        display_frame = cv2.resize(display_frame, None, fx=scale, fy=scale)
                    cv2.imshow(config.get("display", {}).get("window_name", "Smart Box Counter"), display_frame)
                    if config.get("display", {}).get("show_mask") and result.mask is not None:
                        cv2.imshow("Motion mask", result.mask)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
                if args.max_frames and frames >= args.max_frames:
                    break
        finally:
            capture.release()
            csv_path = pipeline.export_csv()
            total = pipeline.store.total()
            pipeline.close()
            cv2.destroyAllWindows()
        print(f"Finished: {frames} frames, {total} boxes. CSV: {csv_path}")
        return 0
    except (FileNotFoundError, ValueError, RuntimeError, cv2.error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
