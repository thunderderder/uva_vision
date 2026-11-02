"""证据图：原图 JPEG + 画框 JPEG。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from uva.paths import ensure_pipeline_importable


def save_jpeg(path: Path, rgb: np.ndarray, quality: int = 90) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return path


def draw_alerts(rgb: np.ndarray, alerts: list[dict[str, Any]]) -> np.ndarray:
    ensure_pipeline_importable()
    from modules.visual_prompter import VisualPrompter

    dets = []
    for alert in alerts:
        item = dict(alert)
        item.setdefault("bbox", item.get("global_bbox"))
        item.setdefault("id", item.get("id", 0))
        dets.append(item)
    prompter = VisualPrompter(color=(255, 32, 32), thickness=3, font_scale=1.0)
    return prompter.inject_prompt(rgb, dets, bbox_key="global_bbox")


def _maybe_draw_detect_roi(
    rgb: np.ndarray,
    roi_norm: list[float] | tuple[float, ...] | None,
    *,
    enabled: bool = True,
) -> np.ndarray:
    if not enabled or not roi_norm:
        return rgb
    from uva.detect_roi import clamp_norm, draw_roi_rect, norm_to_xyxy

    norm = clamp_norm(roi_norm)
    if norm is None:
        return rgb
    h, w = rgb.shape[:2]
    xyxy = norm_to_xyxy(norm, w, h)
    return draw_roi_rect(rgb, xyxy)


def write_job_evidence(
    evidence_dir: Path,
    job_id: str,
    rgb: np.ndarray,
    alerts: list[dict[str, Any]],
    *,
    roi_norm: list[float] | tuple[float, ...] | None = None,
    draw_detect_roi: bool = True,
) -> dict[str, str]:
    job_dir = evidence_dir / job_id
    base = _maybe_draw_detect_roi(rgb, roi_norm, enabled=draw_detect_roi)
    raw_path = save_jpeg(job_dir / "original.jpg", base)
    boxed = draw_alerts(base, alerts) if alerts else base
    det_path = save_jpeg(job_dir / "detected.jpg", boxed)
    return {"original": str(raw_path), "detected": str(det_path)}
