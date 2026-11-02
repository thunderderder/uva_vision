"""切片 YOLO 检测 + 全图类无关 NMS（与 kernel.infer_frame 约定一致）。"""

from __future__ import annotations

from typing import Any

from modules.global_box_nms import class_agnostic_nms


def _offset_bbox(bbox: list[int], x_offset: int, y_offset: int) -> list[int]:
    x1, y1, x2, y2 = bbox
    return [int(x1 + x_offset), int(y1 + y_offset), int(x2 + x_offset), int(y2 + y_offset)]


def run_yolo_direct_on_rgb(rgb, cfg: dict[str, Any], detector) -> list[dict[str, Any]]:
    """整图（或已裁 ROI）一次 YOLO，不做切片。适用于 1080p RTMP 等场景。"""
    merged: list[dict[str, Any]] = []
    for det in detector.detect(rgb):
        bbox = det.get("bbox") or det.get("global_bbox")
        if not bbox:
            continue
        global_bbox = [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]
        merged.append(
            {
                "id": det.get("id"),
                "bbox": global_bbox,
                "global_bbox": global_bbox,
                "class_name": det.get("class_name"),
                "confidence": det.get("confidence"),
            }
        )
    return class_agnostic_nms(
        merged,
        float(cfg["GLOBAL_CLASS_AGNOSTIC_NMS_IOU"]),
        "global_bbox",
        float(cfg["GLOBAL_CLASS_AGNOSTIC_NMS_IOF"]),
    )


def run_yolo_global_nms_on_rgb(
    rgb,
    cfg: dict[str, Any],
    slicer,
    detector,
) -> list[dict[str, Any]]:
    tiles = slicer.slice_rgb(rgb)
    merged: list[dict[str, Any]] = []
    for tile in tiles:
        x_off = int(tile["x_offset"])
        y_off = int(tile["y_offset"])
        for det in detector.detect(tile["image"]):
            bbox = det.get("bbox") or det.get("global_bbox")
            if not bbox:
                continue
            global_bbox = _offset_bbox(list(bbox), x_off, y_off)
            merged.append(
                {
                    "id": det.get("id"),
                    "bbox": global_bbox,
                    "global_bbox": global_bbox,
                    "class_name": det.get("class_name"),
                    "confidence": det.get("confidence"),
                }
            )
    return class_agnostic_nms(
        merged,
        float(cfg["GLOBAL_CLASS_AGNOSTIC_NMS_IOU"]),
        "global_bbox",
        float(cfg["GLOBAL_CLASS_AGNOSTIC_NMS_IOF"]),
    )
