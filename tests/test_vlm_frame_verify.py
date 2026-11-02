import numpy as np

from uva.paths import ensure_pipeline_importable

ensure_pipeline_importable()
from modules.postprocessor import Postprocessor
from modules.visual_prompter import VisualPrompter
from modules.vlm_frame_verify import run_vlm_verify
from modules.vlm_parse import parse_vlm_output

CFG = {
    "CLASSES_TO_FIND": ["fishing", "swimming"],
    "VLM_PROMPT_TEMPLATE": "ids={ids_str} classes={classes_str}",
    "VLM_MAX_NEW_TOKENS": 64,
    "VLM_CONTEXT_MARGIN_MIN": 8,
    "VLM_CONTEXT_MARGIN_RATIO": 0.1,
}


class _Recorder:
    def __init__(self):
        self.calls = []

    def verify(self, image_array, classes_to_find, detections, prompt_template, max_new_tokens):
        self.calls.append(
            {
                "shape": tuple(image_array.shape[:2]),
                "ids": [d["id"] for d in detections],
                "prompt": prompt_template.format_map(
                    {"ids_str": ", ".join(str(d["id"]) for d in detections), "classes_str": ", ".join(classes_to_find)}
                ),
            }
        )
        lines = []
        for det in detections:
            lines.append(f"ID: {det['id']}, Type: swimming")
            lines.append(f"Description: box {det['id']}")
        return parse_vlm_output("\n".join(lines))


def _dets():
    return [
        {"id": 1, "global_bbox": [10, 10, 40, 40], "class_name": "person", "confidence": 0.2},
        {"id": 2, "global_bbox": [80, 20, 120, 70], "class_name": "person", "confidence": 0.1},
    ]


def test_full_frame_calls_qwen_once_on_whole_image():
    rgb = np.zeros((180, 240, 3), dtype=np.uint8)
    verifier = _Recorder()
    qwen, alarms, _ = run_vlm_verify(
        rgb, CFG, _dets(), VisualPrompter(), verifier, Postprocessor(CFG["CLASSES_TO_FIND"]), layout="full_frame"
    )
    assert len(verifier.calls) == 1
    assert verifier.calls[0]["shape"] == (180, 240)
    assert verifier.calls[0]["ids"] == [1, 2]
    assert "1, 2" in verifier.calls[0]["prompt"]
    assert [item["detection_id"] for item in qwen] == [1, 2]
    assert qwen[0]["description"] == "box 1"
    assert qwen[1]["description"] == "box 2"
    assert {a["id"] for a in alarms if a["status"] == "confirmed_alarm"} == {1, 2}
    assert alarms[0]["yolo_confidence"] == 0.2
    assert alarms[1]["yolo_confidence"] == 0.1


def test_per_box_still_calls_once_per_detection():
    rgb = np.zeros((180, 240, 3), dtype=np.uint8)
    verifier = _Recorder()
    run_vlm_verify(
        rgb, CFG, _dets(), VisualPrompter(), verifier, Postprocessor(CFG["CLASSES_TO_FIND"]), layout="per_box"
    )
    assert len(verifier.calls) == 2
    assert verifier.calls[0]["ids"] == [1]
    assert verifier.calls[1]["ids"] == [2]
    assert verifier.calls[0]["shape"] != (180, 240)
