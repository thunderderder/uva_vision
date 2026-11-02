"""全图尺度类无关 NMS：合并切片重叠与「小框套大框」导致的重复框，不区分类别。"""


def _inter_and_areas_xyxy(a, b):
    ax1, ay1, ax2, ay2 = (float(x) for x in a)
    bx1, by1, bx2, by2 = (float(x) for x in b)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter, area_a, area_b


def _iou_xyxy(a, b):
    inter, area_a, area_b = _inter_and_areas_xyxy(a, b)
    union = area_a + area_b - inter
    return (inter / union) if union > 0 else 0.0


def _io_min_xyxy(a, b):
    """
    交集 / min(面积)。小框几乎完全落在大框内时接近 1，而标准 IoU 可能仍很小。
    用于抑制「同心大小框」这类 NMS 漏网之鱼。
    """
    inter, area_a, area_b = _inter_and_areas_xyxy(a, b)
    m = min(area_a, area_b)
    return (inter / m) if m > 0 else 0.0


def _should_suppress(anchor, other, iou_threshold, iof_threshold):
    """当前保留框 anchor 是否应抑制候选框 other（二者置信度已保证 anchor 更高）。"""
    if iou_threshold < 1.0 and _iou_xyxy(anchor, other) > iou_threshold:
        return True
    if iof_threshold < 1.0 and _io_min_xyxy(anchor, other) > iof_threshold:
        return True
    return False


def class_agnostic_nms(
    detections,
    iou_threshold,
    bbox_key="global_bbox",
    iof_threshold=0.55,
):
    """
    Greedy class-agnostic NMS on detections sorted by confidence (desc).

    - iou_threshold >= 1.0: 不使用 IoU 抑制。
    - iof_threshold >= 1.0: 不使用 IOF（交集/min(面积)，嵌套框）抑制。
    - 二者均 >= 1.0 时仅重编号。
    """
    if not detections:
        return []

    if iou_threshold >= 1.0 and iof_threshold >= 1.0:
        return _renumber_ids(detections)

    missing = [i for i, d in enumerate(detections) if bbox_key not in d]
    if missing:
        raise KeyError(f"class_agnostic_nms: missing {bbox_key} on detections indices {missing[:5]}...")

    n = len(detections)
    order = sorted(
        range(n),
        key=lambda i: float(detections[i].get("confidence", 0.0)),
        reverse=True,
    )
    boxes = [detections[i][bbox_key] for i in range(n)]

    keep_idx = []
    remaining = list(order)
    while remaining:
        i = remaining.pop(0)
        keep_idx.append(i)
        bi = boxes[i]
        new_remaining = []
        for j in remaining:
            if not _should_suppress(bi, boxes[j], iou_threshold, iof_threshold):
                new_remaining.append(j)
        remaining = new_remaining

    keep_idx.sort(key=lambda idx: float(detections[idx].get("confidence", 0.0)), reverse=True)
    picked = [detections[idx].copy() for idx in keep_idx]
    return _renumber_ids(picked)


def _renumber_ids(detections):
    out = []
    for new_id, d in enumerate(detections, start=1):
        c = d.copy()
        c["id"] = new_id
        out.append(c)
    return out
