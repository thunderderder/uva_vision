from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRA_SRC = ROOT / "src"
for p in (str(PRA_SRC),):
    if p not in sys.path:
        sys.path.insert(0, p)

import uva_pra.runtime_ui as runtime_ui
from uva_pra.runtime_ui import list_frozen_prompts, runtime_from_frozen, save_frozen_prompt, validate_frozen_id


def test_validate_frozen_id():
    assert validate_frozen_id("p1_v_20261019") == "p1_v_20261019"
    try:
        validate_frozen_id("bad id")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_save_frozen_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_ui, "_FROZEN_DIR", tmp_path)
    prompt = "测试冻词 {ids_str} [{classes_str}]"
    saved = save_frozen_prompt(
        "test_pra_v1",
        purpose="单元测试",
        prompt_template=prompt,
        classes_to_find=["fishing"],
        yolo_classes=["person"],
        layout={"file": "full_frame", "rtmp": "per_box"},
        yolo_conf=0.02,
    )
    assert Path(saved["json_path"]).is_file()
    assert Path(saved["prompt_path"]).read_text(encoding="utf-8") == prompt
    meta = json.loads(Path(saved["json_path"]).read_text(encoding="utf-8"))
    assert meta["yolo_conf"] == 0.02
    assert meta["layout"]["rtmp"] == "per_box"

    items = list_frozen_prompts()
    assert any(x["id"] == "test_pra_v1" for x in items)
    rt = runtime_from_frozen("test_pra_v1")
    assert rt["VLM_PROMPT_TEMPLATE"] == prompt
    assert rt["YOLO_CLASSES"] == ["person"]
    assert rt["YOLO_CONF_THRESHOLD"] == 0.02


def test_save_frozen_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_ui, "_FROZEN_DIR", tmp_path)
    save_frozen_prompt(
        "dup_test",
        purpose="a",
        prompt_template="x",
        classes_to_find=[],
        yolo_classes=["person"],
        layout={"file": "full_frame", "rtmp": "full_frame"},
    )
    try:
        save_frozen_prompt(
            "dup_test",
            purpose="b",
            prompt_template="y",
            classes_to_find=[],
            yolo_classes=["person"],
            layout={"file": "full_frame", "rtmp": "full_frame"},
        )
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass
