from __future__ import annotations

import numpy as np

from uva.detect_roi import crop_rgb, normalize_roi_tuple, offset_detections, resolve_detect_roi_norm


def test_normalize_roi_rejects_tiny():
    assert normalize_roi_tuple([0, 0, 0.001, 0.5]) is None


def test_crop_and_offset():
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    norm = [0.1, 0.2, 0.9, 0.8]
    crop, off = crop_rgb(rgb, norm)
    assert crop.shape[0] == 60
    assert crop.shape[1] == 160
    dets = [{"bbox": [5, 5, 10, 10], "global_bbox": [5, 5, 10, 10], "class_name": "person"}]
    out = offset_detections(dets, off)
    assert out[0]["global_bbox"][0] == 5 + off[0]


def test_resolve_by_source():
    cfg = {"DETECT_ROI_BY_SOURCE": {"rtmp": [0.0, 0.0, 1.0, 1.0]}}
    assert resolve_detect_roi_norm("rtmp", cfg) == [0.0, 0.0, 1.0, 1.0]
    assert resolve_detect_roi_norm("file", cfg) == [0.0, 0.0, 1.0, 1.0]
    cfg_file = {"DETECT_ROI_BY_SOURCE": {"file": [0.2, 0.2, 0.8, 0.8]}}
    assert resolve_detect_roi_norm("file", cfg_file) == [0.2, 0.2, 0.8, 0.8]
    cfg2 = {"DETECT_ROI_BY_SOURCE": {"file": [0.1, 0.1, 0.9, 0.9]}}
    assert resolve_detect_roi_norm("file", cfg2) == [0.1, 0.1, 0.9, 0.9]
