from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PIPELINE = SRC / "pipeline"
for p in (str(SRC), str(PIPELINE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from modules.detector import ZeroShotDetector, is_world_weights


def test_is_world_weights():
    assert is_world_weights(r"model\yolo\yolov8s-world.pt")
    assert is_world_weights("/x/yolov8m-worldv2.pt")
    assert not is_world_weights("yolov8s.pt")
    assert not is_world_weights("yolov5s.pt")


def test_closed_set_class_name_filter():
    det = ZeroShotDetector.__new__(ZeroShotDetector)
    det._world = False
    det.classes_to_find = ["person", "boat"]
    det._allowed_names = {"person", "boat"}
    names = {0: "person", 8: "boat", 2: "car"}
    assert det._class_name_for_index(0, names) == "person"
    assert det._class_name_for_index(8, names) == "boat"
    assert det._class_name_for_index(2, names) is None


def test_world_class_name_by_index():
    det = ZeroShotDetector.__new__(ZeroShotDetector)
    det._world = True
    det.classes_to_find = ["person", "boat"]
    assert det._class_name_for_index(0, {}) == "person"
    assert det._class_name_for_index(1, {}) == "boat"
    assert det._class_name_for_index(2, {}) is None
