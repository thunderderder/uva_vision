from pathlib import Path

from uva.kernel import resolve_vlm_layout, runtime_config
from uva.paths import PROJECT_ROOT, ensure_pipeline_importable


def test_pipeline_importable_without_chdir():
    ensure_pipeline_importable()
    import config
    from modules.frame_detect import run_yolo_global_nms_on_rgb
    from modules.global_box_nms import class_agnostic_nms

    assert Path(config.BASE_DIR) == PROJECT_ROOT
    assert "person" in config.YOLO_CLASSES
    assert "fishing" in config.CLASSES_TO_FIND
    prompt = config.VLM_PROMPT_TEMPLATE
    assert "{ids_str}" in prompt
    assert "{classes_str}" in prompt
    assert "false_detect" in prompt
    assert "Type: fishing/swimming" not in prompt
    assert "大概率" not in prompt
    assert "城市河道" not in prompt
    assert "人在岸上写 person_ok" not in prompt
    assert "先看是不是人" in prompt
    assert "{ids_str}" in prompt
    assert config.VLM_LAYOUT_BY_SOURCE["rtmp"] == "full_frame"
    assert config.VLM_LAYOUT_BY_SOURCE["file"] == "full_frame"
    debris = config.build_vlm_prompt_template(
        ["fishing", "swimming", "debris"],
        {"debris": "水面异质漂浮物则预警。"},
    )
    assert "debris" in debris
    assert "水面异质漂浮物" in debris
    assert callable(run_yolo_global_nms_on_rgb)
    assert callable(class_agnostic_nms)
    cfg = runtime_config()
    assert resolve_vlm_layout("rtmp", cfg) == "full_frame"
    assert resolve_vlm_layout("file", cfg) == "full_frame"
    assert resolve_vlm_layout(None, cfg) == "full_frame"
