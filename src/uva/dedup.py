"""空间桶冷却：过期前同一格不重复送千问（RTMP 默认约 2s，见 UVA_COOLDOWN_S）。"""

from __future__ import annotations

from typing import Any

from uva.store import Store


def bbox_center(bbox: list[float] | tuple[float, ...]) -> tuple[float, float]:
    x1, y1, x2, y2 = (float(x) for x in bbox)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def bucket_key(kind: str, bbox: list[float], grid: int) -> str:
    cx, cy = bbox_center(bbox)
    return f"{kind}:{int(cx // grid)}:{int(cy // grid)}"


def person_bucket(det: dict[str, Any], grid: int) -> str:
    bbox = det.get("global_bbox") or det.get("bbox") or [0, 0, 0, 0]
    return bucket_key("person", bbox, grid)


def alert_bucket(alert_type: str, det: dict[str, Any], grid: int) -> str:
    bbox = det.get("global_bbox") or det.get("bbox") or det.get("global_bbox") or [0, 0, 0, 0]
    return bucket_key(alert_type, bbox, grid)


def should_skip(store: Store, bucket: str, now_ts: float, cooldown_s: float) -> bool:
    row = store.get_dedup(bucket)
    if row is None:
        return False
    return (now_ts - float(row["last_ts"])) < cooldown_s
