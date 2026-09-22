import cv2
import numpy as np
import pytest

from src.color import HSVColorClassifier


@pytest.fixture
def classifier():
    return HSVColorClassifier(
        {
            "inner_crop_ratio": 0.1,
            "min_coverage": 0.08,
            "ranges": {
                "red": [{"lower": [0, 80, 45], "upper": [10, 255, 255]}, {"lower": [170, 80, 45], "upper": [179, 255, 255]}],
                "blue": [{"lower": [95, 70, 40], "upper": [135, 255, 255]}],
                "green": [{"lower": [35, 55, 35], "upper": [90, 255, 255]}],
                "yellow": [{"lower": [18, 80, 80], "upper": [35, 255, 255]}],
                "white": [{"lower": [0, 0, 170], "upper": [179, 65, 255]}],
                "black": [{"lower": [0, 0, 0], "upper": [179, 255, 55]}],
                "brown": [{"lower": [5, 60, 25], "upper": [22, 255, 190]}],
            },
        }
    )


@pytest.mark.parametrize(
    "name,bgr",
    [("red", (0, 0, 220)), ("blue", (220, 60, 20)), ("green", (30, 170, 30)), ("yellow", (0, 220, 220)), ("white", (230, 230, 230)), ("black", (20, 20, 20)), ("brown", (25, 80, 135))],
)
def test_supported_colors(classifier, name, bgr):
    frame = np.full((100, 100, 3), bgr, dtype=np.uint8)
    predicted, confidence = classifier.classify(frame, (0, 0, 100, 100))
    assert predicted == name
    assert confidence > 0.9


def test_invalid_crop_is_unknown(classifier):
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert classifier.classify(frame, (20, 20, 4, 4)) == ("unknown", 0.0)
