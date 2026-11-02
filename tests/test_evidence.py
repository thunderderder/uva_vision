import numpy as np

from uva.evidence import draw_alerts
from uva.paths import ensure_pipeline_importable

ensure_pipeline_importable()
from modules.postprocessor import Postprocessor
from modules.visual_prompter import box_label


def test_box_label_prefers_yolo_confidence():
    assert box_label({"id": 1, "confidence": "high", "yolo_confidence": 0.057}) == "[1] 0.057"
    assert box_label({"id": 2, "confidence": 0.2}) == "[2] 0.200"
    assert box_label({"id": 3, "confidence": "low"}) == "[3]"


def test_postprocessor_keeps_yolo_confidence():
    out = Postprocessor(["fishing", "swimming"]).process(
            [{"id": 1, "class_name": "person", "confidence": 0.057, "bbox": [1, 2, 3, 4], "global_bbox": [1, 2, 3, 4]}],
        {"verified_objects": [{"id": 1, "type": "fishing"}]},
    )
    alarm = out["alarms"][0]
    assert alarm["confidence"] == "high"
    assert alarm["yolo_confidence"] == 0.057


def test_draw_alerts_accepts_string_confidence():
    rgb = np.zeros((64, 64, 3), dtype=np.uint8)
    out = draw_alerts(
        rgb,
        [
            {
                "id": 1,
                "global_bbox": [4, 4, 40, 40],
                "confidence": "high",
            }
        ],
    )
    assert out.shape == rgb.shape
    assert not np.array_equal(out, rgb)
