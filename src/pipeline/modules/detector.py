"""Ultralytics YOLO-World 或闭集 YOLOv8 检测；类别过滤统一用英文类名（词），不用 COCO 数字 ID。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def is_world_weights(model_path: str) -> bool:
    """根据权重文件名判断是否为 YOLO-World（与 Ultralytics 约定一致）。"""
    stem = Path(model_path).stem.lower()
    return "-world" in stem or "worldv2" in stem


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower()


class ZeroShotDetector:
    """World：set_classes 后 cls 下标对应 YOLO_CLASSES 列表。闭集 v8：按 COCO 类名过滤 YOLO_CLASSES。"""

    def __init__(
        self,
        model_path: str,
        classes_to_find: list[str],
        conf_threshold: float = 0.25,
        class_conf_threshold: dict[str, float] | None = None,
    ) -> None:
        self.conf_threshold = float(conf_threshold)
        self.class_conf_threshold = dict(class_conf_threshold or {})
        self.classes_to_find = [str(c).strip() for c in classes_to_find if str(c).strip()]
        self._world = is_world_weights(model_path)

        if self._world:
            from ultralytics import YOLOWorld

            self.model = YOLOWorld(model_path)
            self.model.set_classes(self.classes_to_find)
            self._allowed_names: set[str] | None = None
        else:
            from ultralytics import YOLO

            self.model = YOLO(model_path)
            self._allowed_names = {_normalize_name(c) for c in self.classes_to_find}

    def _class_name_for_index(self, cls_idx: int, result_names: Any) -> str | None:
        if self._world:
            if cls_idx < 0 or cls_idx >= len(self.classes_to_find):
                return None
            return self.classes_to_find[cls_idx]

        raw: str | None = None
        if isinstance(result_names, dict):
            raw = result_names.get(int(cls_idx)) or result_names.get(cls_idx)
        elif result_names is not None:
            try:
                raw = result_names[int(cls_idx)]
            except (KeyError, IndexError, TypeError):
                raw = None
        if raw is None:
            return None
        name = str(raw).strip()
        if self._allowed_names and _normalize_name(name) not in self._allowed_names:
            return None
        return name

    def detect(self, image: Any) -> list[dict[str, Any]]:
        results = self.model.predict(image, conf=self.conf_threshold, verbose=False)
        result = results[0]
        detections: list[dict[str, Any]] = []
        names = result.names

        for box in result.boxes:
            xyxy = box.xyxy[0].cpu().numpy().astype(int)
            x1, y1, x2, y2 = (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))
            conf = float(box.conf[0].cpu().numpy())
            cls_idx = int(box.cls[0].cpu().numpy())
            class_name = self._class_name_for_index(cls_idx, names)
            if not class_name:
                continue

            min_conf = float(
                self.class_conf_threshold.get(class_name, self.class_conf_threshold.get(_normalize_name(class_name), self.conf_threshold))
            )
            if conf < min_conf:
                continue

            detections.append(
                {
                    "id": len(detections) + 1,
                    "bbox": [x1, y1, x2, y2],
                    "class_name": class_name,
                    "confidence": conf,
                }
            )
        return detections
