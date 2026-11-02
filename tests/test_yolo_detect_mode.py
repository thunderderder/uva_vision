from __future__ import annotations

import numpy as np

from uva.detect_roi import localize_detections
from uva.kernel import resolve_yolo_detect_mode, resolve_vlm_layout


def test_localize_detections_subtracts_offset():
    dets = [{"id": 1, "global_bbox": [110, 210, 130, 230], "class_name": "person"}]
    out = localize_detections(dets, (100, 200))
    assert out[0]["global_bbox"] == [10, 10, 30, 30]


def test_resolve_yolo_mode_direct_for_rtmp():
    cfg = {"YOLO_DETECT_MODE_BY_SOURCE": {"rtmp": "direct", "file": "direct"}, "YOLO_AUTO_SLICE_MAX_EDGE": 1920}
    assert resolve_yolo_detect_mode("rtmp", cfg, (1080, 1920, 3)) == "direct"


def test_resolve_yolo_mode_auto_slice_for_4k():
    cfg = {"YOLO_DETECT_MODE_BY_SOURCE": {"file": "auto"}, "YOLO_AUTO_SLICE_MAX_EDGE": 1920}
    assert resolve_yolo_detect_mode("file", cfg, (2160, 3840, 3)) == "slice"
    assert resolve_yolo_detect_mode("file", cfg, (1080, 1920, 3)) == "direct"


def test_resolve_vlm_layout_roi_frame_default():
    cfg = {"VLM_LAYOUT_BY_SOURCE": {"rtmp": "roi_frame", "file": "roi_frame"}}
    assert resolve_vlm_layout("file", cfg) == "roi_frame"
