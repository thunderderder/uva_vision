from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uva_pra.runtime_ui import (
    list_frozen_prompts,
    qwen_vl_presets,
    runtime_field_schema,
    runtime_from_frozen,
    yolo_weight_presets,
)


def test_runtime_schema_has_kernel_keys():
    schema = runtime_field_schema()
    keys = set()
    for group in schema["groups"]:
        for field in group["fields"]:
            k = field["key"]
            if k.startswith("VLM_LAYOUT_BY_SOURCE."):
                continue
            keys.add(k)
    assert "YOLO_CLASSES" in keys
    assert "YOLO_WEIGHTS_PATH" in keys
    assert "VLM_PROMPT_TEMPLATE" in keys
    assert "CLASSES_TO_FIND" in keys


def test_qwen_vl_presets_has_2b_and_4b():
    presets = qwen_vl_presets()
    ids = {p["id"] for p in presets}
    assert "qwen3_vl_2b" in ids
    assert "qwen3_vl_4b" in ids
    for p in presets:
        assert p["backend"] == "local"
        assert "qwen-vl" in p["path"].replace("\\", "/").lower()


def test_yolo_weight_presets_has_world_and_v8s():
    presets = yolo_weight_presets()
    ids = {p["id"] for p in presets}
    assert "yolov8s_world" in ids
    assert "yolov8s" in ids
    assert any("yolov8s-world" in p["path"] for p in presets)
    v8s = next(p for p in presets if p["id"] == "yolov8s")
    assert v8s["path"].lower().endswith("yolov8s.pt")
    assert "model" in v8s["path"].replace("\\", "/").lower()


def test_frozen_p1_expands():
    items = list_frozen_prompts()
    assert any(x["id"] == "p1_v1_20260904" for x in items)
    rt = runtime_from_frozen("p1_v1_20260904")
    assert rt["YOLO_CLASSES"] == ["person"]
    assert "fishing" in rt["CLASSES_TO_FIND"]
    assert len(rt["VLM_PROMPT_TEMPLATE"]) > 100
    assert rt["_frozen_prompt_id"] == "p1_v1_20260904"
