from __future__ import annotations

import cv2
import numpy as np

from .config import save_config


COLOR_KEYS = {ord("1"): "red", ord("2"): "blue", ord("3"): "green", ord("4"): "yellow", ord("5"): "white", ord("6"): "black", ord("7"): "brown"}


def run_calibration(capture: cv2.VideoCapture, config: dict) -> None:
    """Interactive single-window calibration. Changes are saved on exit."""
    window = "Calibration"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.createTrackbar("Line %", window, int(config["counting_line"]["position"] * 100), 100, lambda _: None)
    state = {"color": "red", "hsv": None, "drag_start": None, "drag_end": None}

    def load_color_trackbars(color: str) -> None:
        ranges = config["color_detection"]["ranges"][color]
        lower, upper = ranges[0]["lower"], ranges[0]["upper"]
        limits = (179, 255, 255, 179, 255, 255)
        for name, value, limit in zip(("H low", "S low", "V low", "H high", "S high", "V high"), lower + upper, limits):
            try:
                cv2.setTrackbarPos(name, window, int(value))
            except cv2.error:
                cv2.createTrackbar(name, window, int(value), limit, lambda _: None)

    def mouse(event, x, y, flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            state["drag_start"] = (x, y)
            state["drag_end"] = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_LBUTTON:
            state["drag_end"] = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            state["drag_end"] = (x, y)
        elif event == cv2.EVENT_RBUTTONDOWN:
            state["sample_point"] = (x, y)

    cv2.setMouseCallback(window, mouse)
    load_color_trackbars("red")
    last_shape = None
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        last_shape = frame.shape
        height, width = frame.shape[:2]
        line_percent = cv2.getTrackbarPos("Line %", window)
        config["counting_line"]["position"] = max(0.0, min(1.0, line_percent / 100.0))
        line_y = round(height * config["counting_line"]["position"])
        cv2.line(frame, (0, line_y), (width, line_y), (0, 165, 255), 3)

        start, end = state.get("drag_start"), state.get("drag_end")
        if start and end:
            x1, x2 = sorted((max(0, start[0]), min(width - 1, end[0])))
            y1, y2 = sorted((max(0, start[1]), min(height - 1, end[1])))
            if x2 > x1 and y2 > y1:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 255), 2)

        point = state.pop("sample_point", None)
        if point and 0 <= point[0] < width and 0 <= point[1] < height:
            pixel = frame[point[1] : point[1] + 1, point[0] : point[0] + 1]
            state["hsv"] = tuple(int(v) for v in cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0, 0])
        instructions = f"Color: {state['color']} | HSV: {state['hsv']} | 1-7 color, drag ROI, right-click sample, S save, Q quit"
        cv2.putText(frame, instructions, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow(window, frame)

        current_range = config["color_detection"]["ranges"][state["color"]][0]
        current_range["lower"] = [cv2.getTrackbarPos(name, window) for name in ("H low", "S low", "V low")]
        current_range["upper"] = [cv2.getTrackbarPos(name, window) for name in ("H high", "S high", "V high")]
        key = cv2.waitKey(1) & 0xFF
        if key in COLOR_KEYS:
            state["color"] = COLOR_KEYS[key]
            load_color_trackbars(state["color"])
        elif key in (ord("s"), ord("S")):
            if start and end and last_shape:
                x1, x2 = sorted((start[0], end[0])); y1, y2 = sorted((start[1], end[1]))
                if x2 > x1 and y2 > y1:
                    config["roi"] = {"x": x1 / width, "y": y1 / height, "width": (x2 - x1) / width, "height": (y2 - y1) / height}
            save_config(config)
            print(f"Calibration saved to {config['_config_path']}")
        elif key in (ord("q"), 27):
            break

    if state.get("drag_start") and state.get("drag_end") and last_shape:
        height, width = last_shape[:2]
        x1, x2 = sorted((state["drag_start"][0], state["drag_end"][0]))
        y1, y2 = sorted((state["drag_start"][1], state["drag_end"][1]))
        if x2 > x1 and y2 > y1:
            config["roi"] = {"x": x1 / width, "y": y1 / height, "width": (x2 - x1) / width, "height": (y2 - y1) / height}
    save_config(config)
    cv2.destroyWindow(window)
