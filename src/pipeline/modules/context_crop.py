"""按检测框裁 VLM 上下文块（per_box 布局用）。"""

from __future__ import annotations

import numpy as np


def context_crop_and_local_box(
    full_img: np.ndarray,
    global_bbox: list[int] | tuple[int, ...],
    margin_min: int,
    margin_ratio: float,
) -> tuple[np.ndarray, list[int]]:
    h, w = full_img.shape[:2]
    gx1, gy1, gx2, gy2 = (int(round(float(x))) for x in global_bbox)
    gx1 = max(0, min(gx1, w - 1))
    gy1 = max(0, min(gy1, h - 1))
    gx2 = max(gx1 + 1, min(gx2, w))
    gy2 = max(gy1 + 1, min(gy2, h))
    bw, bh = gx2 - gx1, gy2 - gy1
    margin = max(int(margin_min), int(margin_ratio * max(bw, bh)))
    cx1 = max(0, gx1 - margin)
    cy1 = max(0, gy1 - margin)
    cx2 = min(w, gx2 + margin)
    cy2 = min(h, gy2 + margin)
    crop = full_img[cy1:cy2, cx1:cx2].copy()
    local_bbox = [gx1 - cx1, gy1 - cy1, gx2 - cx1, gy2 - cy1]
    return crop, local_bbox
