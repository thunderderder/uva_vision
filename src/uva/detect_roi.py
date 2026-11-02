"""检测 ROI：裁切 YOLO / 千问输入区域，框坐标映射回全图（存证仍用原图）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class DetectRoiView:
    enabled: bool
    norm: tuple[float, float, float, float] | None
    xyxy: tuple[int, int, int, int] | None
    offset_x: int
    offset_y: int

    def crop_rgb(self, rgb: np.ndarray) -> np.ndarray:
        if not self.enabled or self.xyxy is None:
            return rgb
        x1, y1, x2, y2 = self.xyxy
        return rgb[y1:y2, x1:x2].copy()


def clamp_norm(norm: list[float] | tuple[float, ...]) -> tuple[float, float, float, float] | None:
    if not norm or len(norm) != 4:
        return None
    x1, y1, x2, y2 = (float(norm[0]), float(norm[1]), float(norm[2]), float(norm[3]))
    x1, x2 = sorted((max(0.0, min(1.0, x1)), max(0.0, min(1.0, x2))))
    y1, y2 = sorted((max(0.0, min(1.0, y1)), max(0.0, min(1.0, y2))))
    if x2 - x1 < 0.02 or y2 - y1 < 0.02:
        return None
    return (x1, y1, x2, y2)


def norm_to_xyxy(norm: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = norm
    return (
        int(round(x1 * width)),
        int(round(y1 * height)),
        int(round(x2 * width)),
        int(round(y2 * height)),
    )


def resolve_detect_roi(
    cfg: dict[str, Any],
    *,
    source_type: str = "rtmp",
    width: int,
    height: int,
) -> DetectRoiView:
    """从 runtime cfg 解析 ROI；preset 可覆盖 DETECT_ROI_ENABLED / DETECT_ROI_NORM。"""
    enabled = bool(cfg.get("DETECT_ROI_ENABLED"))
    norm_raw = cfg.get("DETECT_ROI_NORM")
    if not enabled:
        return DetectRoiView(enabled=False, norm=None, xyxy=None, offset_x=0, offset_y=0)

    norm = clamp_norm(norm_raw) if norm_raw else None
    if norm is None:
        return DetectRoiView(enabled=False, norm=None, xyxy=None, offset_x=0, offset_y=0)

    x1, y1, x2, y2 = norm_to_xyxy(norm, width, height)
    if x2 <= x1 + 2 or y2 <= y1 + 2:
        return DetectRoiView(enabled=False, norm=None, xyxy=None, offset_x=0, offset_y=0)
    return DetectRoiView(enabled=True, norm=norm, xyxy=(x1, y1, x2, y2), offset_x=x1, offset_y=y1)


def offset_detections_to_full(detections: list[dict[str, Any]], offset_x: int, offset_y: int) -> list[dict[str, Any]]:
    if not offset_x and not offset_y:
        return detections
    out: list[dict[str, Any]] = []
    for det in detections:
        d = dict(det)
        for key in ("bbox", "global_bbox"):
            bbox = d.get(key)
            if not bbox or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = bbox
            d[key] = [int(x1 + offset_x), int(y1 + offset_y), int(x2 + offset_x), int(y2 + offset_y)]
        out.append(d)
    return out


def draw_roi_rect(
    rgb: np.ndarray,
    xyxy: tuple[int, int, int, int],
    *,
    color: tuple[int, int, int] = (0, 220, 120),
    thickness: int = 2,
) -> np.ndarray:
    import cv2

    out = rgb.copy()
    x1, y1, x2, y2 = xyxy
    cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
    label = "detect ROI"
    cv2.putText(
        out,
        label,
        (x1 + 4, max(y1 + 18, 16)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        1,
        cv2.LINE_AA,
    )
    return out


def normalize_roi_tuple(norm: list[float] | tuple[float, ...] | None) -> tuple[float, float, float, float] | None:
    """与 kernel / 单测一致的归一化 ROI 校验。"""
    if norm is None:
        return None
    return clamp_norm(norm)


def crop_rgb(rgb: np.ndarray, norm: list[float] | tuple[float, ...]) -> tuple[np.ndarray, tuple[int, int]]:
    """裁切检测区域，返回 (crop, (offset_x, offset_y))。"""
    n = clamp_norm(norm)
    if n is None:
        return rgb.copy(), (0, 0)
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = norm_to_xyxy(n, w, h)
    return rgb[y1:y2, x1:x2].copy(), (x1, y1)


def offset_detections(
    detections: list[dict[str, Any]],
    offset: tuple[int, int] | list[int],
) -> list[dict[str, Any]]:
    ox, oy = int(offset[0]), int(offset[1])
    return offset_detections_to_full(detections, ox, oy)


def localize_detections(
    detections: list[dict[str, Any]],
    offset: tuple[int, int] | list[int],
) -> list[dict[str, Any]]:
    """全图坐标 → 裁切图局部坐标（千问 roi_frame 用）。"""
    ox, oy = int(offset[0]), int(offset[1])
    if not ox and not oy:
        return [dict(d) for d in detections]
    out: list[dict[str, Any]] = []
    for det in detections:
        d = dict(det)
        for key in ("bbox", "global_bbox"):
            bbox = d.get(key)
            if not bbox or len(bbox) < 4:
                continue
            d[key] = [
                int(bbox[0]) - ox,
                int(bbox[1]) - oy,
                int(bbox[2]) - ox,
                int(bbox[3]) - oy,
            ]
        out.append(d)
    return out


def resolve_detect_roi_norm(source_type: str | None, cfg: dict[str, Any]) -> list[float] | None:
    """按来源取归一化 ROI；未配置或 file 无项时返回 None（整图检测）。"""
    st = (source_type or "file").strip() or "file"
    table = cfg.get("DETECT_ROI_BY_SOURCE") or {}
    raw: Any = table.get(st)
    if raw is None and st == "file":
        raw = table.get("rtmp")
    if raw is None and st == "rtmp" and cfg.get("DETECT_ROI_ENABLED"):
        raw = cfg.get("DETECT_ROI_NORM")
    if raw is None:
        return None
    n = clamp_norm(raw)
    return list(n) if n else None


def by_source_from_yaml_entries(by_source: dict[str, Any] | None) -> dict[str, list[float]]:
    """实验台 detect_roi.yaml → kernel 用的 DETECT_ROI_BY_SOURCE。"""
    out: dict[str, list[float]] = {}
    for src, entry in (by_source or {}).items():
        if not isinstance(entry, dict) or not entry.get("enabled"):
            continue
        n = clamp_norm(entry.get("norm") or [])
        if n:
            out[str(src)] = list(n)
    return out


def roi_settings_for_source(by_source: dict[str, Any] | None, source_type: str) -> dict[str, Any]:
    """把 detect_roi.yaml 的 by_source 项合并进 cfg 形字段。"""
    table = by_source or {}
    entry = table.get(source_type) or table.get("rtmp") or {}
    enabled = bool(entry.get("enabled"))
    norm = entry.get("norm")
    return {
        "DETECT_ROI_ENABLED": enabled,
        "DETECT_ROI_NORM": list(norm) if norm else None,
    }
