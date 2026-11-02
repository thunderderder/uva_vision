"""Pipeline 推理默认配置（路径相对 uva 项目根目录）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = str(PROJECT_ROOT)

MODEL_DIR = PROJECT_ROOT / "model"
DATA_DIR = PROJECT_ROOT / "data"

_YOLO_DIR = MODEL_DIR / "yolo"
_YOLO_V8S_WEIGHTS = os.environ.get("UVA_YOLO_V8S_WEIGHTS", str(_YOLO_DIR / "yolov8s.pt"))
YOLO_WEIGHTS_PATH = str(_YOLO_DIR / "yolov8s-world.pt")
YOLO_WEIGHT_PRESETS: dict[str, str] = {
    "yolov8s_world": str(_YOLO_DIR / "yolov8s-world.pt"),
    "yolov8s": _YOLO_V8S_WEIGHTS,
}
_DEFAULT_QWEN = MODEL_DIR / "vl" / "qwen-vl" / "2B-Instruct"
QWEN_DIR_PATH = os.environ.get("UVA_QWEN_DIR_PATH", str(_DEFAULT_QWEN))
DINO_WEIGHT_PATH = str(MODEL_DIR / "vl" / "dino" / "dinov3_vitb16_pretrain_lvd1689m-73cec8be.pth")

TEST_IMAGE_PATH = str(DATA_DIR / "test_img" / "xnp_20m.jpg")
OUTPUT_DIR = str(DATA_DIR / "output" / "pipeline_run")
MVP_OUTPUT_DIR = str(DATA_DIR / "output" / "mvp_run")
MVP_QWEN_DIR = QWEN_DIR_PATH

FROZEN_PROMPT_ID = "p1_v1_20260904"
_FROZEN_DIR = DATA_DIR / "eval_p1" / "frozen"
_FROZEN_META = json.loads((_FROZEN_DIR / "p1_v1_20260904.json").read_text(encoding="utf-8"))
VLM_PROMPT_TEMPLATE = (_FROZEN_DIR / _FROZEN_META["prompt_file"]).read_text(encoding="utf-8")
VLM_ALERT_GUIDE = dict(_FROZEN_META["vlm_alert_guide"])

YOLO_CLASSES = list(_FROZEN_META.get("yolo_classes") or ["person"])
CLASSES_TO_FIND = list(_FROZEN_META.get("classes_to_find") or ["fishing", "swimming"])
YOLO_CONF_THRESHOLD = float(_FROZEN_META.get("yolo_conf", 0.01))
YOLO_CLASS_CONF_THRESHOLD = {"person": 0.01, "human": 0.01}

SLICER_SIZE = 640
SLICER_OVERLAP_RATIO = 0.2
GLOBAL_CLASS_AGNOSTIC_NMS_IOU = 0.5
GLOBAL_CLASS_AGNOSTIC_NMS_IOF = 0.42

PROMPT_BOX_COLOR = (255, 0, 0)
PROMPT_BOX_THICKNESS = 2
PROMPT_FONT_SCALE = 1.0

VLM_MAX_NEW_TOKENS = 1024
VLM_CONTEXT_MARGIN_MIN = 96
VLM_CONTEXT_MARGIN_RATIO = 0.35
VLM_LAYOUT_BY_SOURCE = dict(
    _FROZEN_META.get("layout") or {"rtmp": "roi_frame", "file": "roi_frame"}
)
# 归一化 [x1,y1,x2,y2]，按 source_type 裁切 YOLO / 千问（roi_frame）输入
DETECT_ROI_BY_SOURCE: dict[str, list[float] | None] = {}
# direct=整图/ROI 一次 YOLO；slice=切片；auto=按 YOLO_AUTO_SLICE_MAX_EDGE 选择
YOLO_DETECT_MODE_BY_SOURCE: dict[str, str] = {"rtmp": "direct", "file": "direct"}
YOLO_AUTO_SLICE_MAX_EDGE = 1920

IMG_SIZE = 1024
PATCH_SIZE = 16
CROP_BOX = (2000, 1500, 3000, 2500)
QUERY_POINT = (12, 22)


def build_vlm_prompt_template(
    classes_to_find: list[str],
    extra_guides: dict[str, str] | None = None,
) -> str:
    """按类别扩展冻词模板（与线上一致，支持临时加类如 debris）。"""
    guides = {**VLM_ALERT_GUIDE, **(extra_guides or {})}
    classes = list(classes_to_find)
    lines = VLM_PROMPT_TEMPLATE.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "按这个顺序判断，不要跳步：":
            out.append(line)
            out.append("1. 先看是不是人。看不出人形，输出 false_detect，到此结束。")
            step = 2
            for cls in classes:
                if cls == "drowning":
                    out.append(f"{step}. 是人，在水中或水面且有溺水征象，输出 drowning。")
                elif cls == "swimming":
                    out.append(f"{step}. 是人，位于水中正常游泳或涉水，输出 swimming。")
                elif cls == "fishing":
                    out.append(f"{step}. 是人，贴着水面（水边坐、蹲、站在水线、船上）垂钓或临水作业，输出 fishing。")
                elif cls == "no_life_jacket":
                    out.append(f"{step}. 是人，在水边或岸边未见救生衣/浮具，且不属于 drowning、swimming、fishing，输出 no_life_jacket。")
                else:
                    out.append(f"{step}. 是人，符合 {cls} 判据，输出 {cls}。")
                step += 1
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("预警环境判据"):
                i += 1
            continue
        if line.strip().startswith("预警环境判据"):
            out.append("预警环境判据：")
            for idx, cls in enumerate(classes, 1):
                hint = guides.get(cls, "")
                out.append(f"{idx}. {cls}：{hint}")
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].startswith("Type "):
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out)
