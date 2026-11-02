"""工作台 runtime 字段：与 uva.kernel.runtime_config 对齐的 UI 元数据与冻词展开。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from uva_pra.bootstrap import PROJECT_ROOT

_YOLO_V8S_WEIGHTS = os.environ.get(
    "UVA_YOLO_V8S_WEIGHTS",
    str(PROJECT_ROOT / "model" / "yolo" / "yolov8s.pt"),
)
_QWEN_VL_2B = os.environ.get(
    "UVA_QWEN_VL_2B_PATH",
    str(PROJECT_ROOT / "model" / "vl" / "qwen-vl" / "2B-Instruct"),
)
_QWEN_VL_4B = os.environ.get(
    "UVA_QWEN_VL_4B_PATH",
    str(PROJECT_ROOT / "model" / "vl" / "qwen-vl" / "4B-Instruct"),
)
_FROZEN_DIR = Path(os.environ.get("UVA_FROZEN_DIR", str(PROJECT_ROOT / "data" / "eval_p1" / "frozen")))
_PRA_META_FROZEN_KEY = "_frozen_prompt_id"
_FROZEN_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{2,63}$")


def list_frozen_prompts() -> list[dict[str, Any]]:
    if not _FROZEN_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(_FROZEN_DIR.glob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = str(meta.get("id") or path.stem)
        out.append(
            {
                "id": pid,
                "purpose": meta.get("purpose") or "",
                "frozen_at": meta.get("frozen_at"),
                "prompt_sha256": meta.get("prompt_sha256"),
                "yolo_classes": list(meta.get("yolo_classes") or []),
                "classes_to_find": list(meta.get("classes_to_find") or []),
            }
        )
    return out


def qwen_vl_presets() -> list[dict[str, str]]:
    """千问 VL 复核（transformers 本地目录 → runtime QWEN_DIR_PATH）。"""
    return [
        {
            "id": "qwen3_vl_2b",
            "label": "Qwen3-VL-2B-Instruct（本地 transformers）",
            "backend": "local",
            "path": _QWEN_VL_2B,
        },
        {
            "id": "qwen3_vl_4b",
            "label": "Qwen3-VL-4B-Instruct（本地 transformers）",
            "backend": "local",
            "path": _QWEN_VL_4B,
        },
    ]


def yolo_weight_presets() -> list[dict[str, str]]:
    """供 Web 下拉切换；权重默认在项目 model/ 下（可用 UVA_YOLO_V8S_WEIGHTS 覆盖）。"""
    world = str(PROJECT_ROOT / "model" / "yolo" / "yolov8s-world.pt")
    return [
        {
            "id": "yolov8s_world",
            "label": "YOLOv8s-World（开放词，默认）",
            "path": world,
        },
        {
            "id": "yolov8s",
            "label": "YOLOv8s（COCO 闭集）",
            "path": _YOLO_V8S_WEIGHTS,
        },
    ]


def validate_frozen_id(frozen_id: str) -> str:
    fid = str(frozen_id or "").strip()
    if not _FROZEN_ID_RE.match(fid):
        raise ValueError("冻词 id 须以字母开头，3–64 字符，仅限字母、数字、下划线、连字符")
    if ".." in fid or "/" in fid or "\\" in fid:
        raise ValueError("冻词 id 非法")
    return fid


def save_frozen_prompt(
    frozen_id: str,
    *,
    purpose: str,
    prompt_template: str,
    classes_to_find: list[str],
    yolo_classes: list[str],
    layout: dict[str, str],
    yolo_conf: float | None = None,
    based_on: str | None = None,
    overwrite: bool = False,
    model_refs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """写入 data/eval_p1/frozen/{id}.json + {id}.prompt.txt。"""
    fid = validate_frozen_id(frozen_id)
    prompt_text = str(prompt_template or "").strip()
    if not prompt_text:
        raise ValueError("VLM_PROMPT_TEMPLATE 不能为空")

    _FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _FROZEN_DIR / f"{fid}.json"
    prompt_path = _FROZEN_DIR / f"{fid}.prompt.txt"
    if json_path.is_file() or prompt_path.is_file():
        if not overwrite:
            raise FileExistsError(f"冻词已存在: {fid}（勾选覆盖或换一个 id）")
    elif overwrite:
        pass

    vlm_alert_guide: dict[str, str] = {}
    if based_on:
        parent_path = _FROZEN_DIR / f"{based_on}.json"
        if parent_path.is_file():
            try:
                parent = json.loads(parent_path.read_text(encoding="utf-8"))
                raw = parent.get("vlm_alert_guide") or {}
                if isinstance(raw, dict):
                    vlm_alert_guide = {str(k): str(v) for k, v in raw.items()}
            except (OSError, json.JSONDecodeError):
                pass

    prompt_sha = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    meta: dict[str, Any] = {
        "id": fid,
        "frozen_at": date.today().isoformat(),
        "purpose": str(purpose or "").strip() or "工作台保存的冻词包",
        "layout": {
            "rtmp": str(layout.get("rtmp") or "full_frame"),
            "file": str(layout.get("file") or "full_frame"),
        },
        "prompt_sha256": prompt_sha,
        "prompt_file": f"{fid}.prompt.txt",
        "classes_to_find": list(classes_to_find),
        "yolo_classes": list(yolo_classes) or ["person"],
        "parser": "允许 ID: [n]；允许同一行 Type 与 Description",
    }
    if vlm_alert_guide:
        meta["vlm_alert_guide"] = vlm_alert_guide
    if yolo_conf is not None:
        meta["yolo_conf"] = float(yolo_conf)
    if based_on:
        meta["based_on"] = based_on
    if model_refs:
        meta["model"] = {k: str(v) for k, v in model_refs.items() if v}

    prompt_path.write_text(prompt_text, encoding="utf-8", newline="\n")
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "frozen_id": fid,
        "json_path": str(json_path),
        "prompt_path": str(prompt_path),
        "prompt_sha256": prompt_sha,
        "meta": meta,
    }


def runtime_from_frozen(frozen_id: str) -> dict[str, Any]:
    meta_path = _FROZEN_DIR / f"{frozen_id}.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"冻词包不存在: {frozen_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    prompt_file = meta.get("prompt_file")
    if not prompt_file:
        raise ValueError(f"冻词元数据缺少 prompt_file: {frozen_id}")
    prompt_path = _FROZEN_DIR / str(prompt_file)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    layout = dict(meta.get("layout") or {"rtmp": "full_frame", "file": "full_frame"})
    yolo_conf = meta.get("yolo_conf")
    runtime: dict[str, Any] = {
        _PRA_META_FROZEN_KEY: frozen_id,
        "YOLO_CLASSES": list(meta.get("yolo_classes") or ["person"]),
        "CLASSES_TO_FIND": list(meta.get("classes_to_find") or []),
        "VLM_PROMPT_TEMPLATE": prompt_text,
        "VLM_LAYOUT_BY_SOURCE": layout,
    }
    if yolo_conf is not None:
        runtime["YOLO_CONF_THRESHOLD"] = float(yolo_conf)
    return runtime


def pra_meta_frozen_key() -> str:
    return _PRA_META_FROZEN_KEY


def runtime_field_schema() -> dict[str, Any]:
    """供前端渲染与文档对照；键名必须与 kernel.runtime_config overrides 一致。"""
    return {
        "version": 1,
        "pra_meta_keys": [_PRA_META_FROZEN_KEY],
        "restart_policy": {
            "worker_restart": "改权重路径、切片尺寸、YOLO 类别、千问目录后需重启 Worker",
            "save_only": "改 VLM_PROMPT_TEMPLATE / CLASSES_TO_FIND 等仍须重启 Worker（当前 worker 启动时读一次配置）",
        },
        "groups": [
            {
                "id": "yolo",
                "title": "YOLO 初筛",
                "fields": [
                    {
                        "key": "YOLO_WEIGHTS_PATH",
                        "type": "yolo_preset",
                        "label": "检测权重",
                        "presets": yolo_weight_presets(),
                        "hint": "World 用开放词；YOLOv8s 闭集请填 COCO 英文类名（如 person, boat），不要填 0/8 等数字 ID。",
                        "restart": "worker",
                    },
                    {
                        "key": "YOLO_CLASSES",
                        "type": "csv",
                        "label": "目标类名（逗号分隔，英文词）",
                        "default_from": "pipeline 冻词默认",
                        "restart": "worker",
                    },
                    {
                        "key": "YOLO_CONF_THRESHOLD",
                        "type": "number",
                        "label": "全局置信度阈值",
                        "min": 0,
                        "max": 1,
                        "step": 0.01,
                        "restart": "worker",
                    },
                    {
                        "key": "YOLO_CLASS_CONF_THRESHOLD",
                        "type": "json_object",
                        "label": "按类别置信度（JSON 对象）",
                        "example": {"person": 0.01},
                        "restart": "worker",
                    },
                ],
            },
            {
                "id": "detect_roi",
                "title": "检测 ROI（仅 YOLO）",
                "fields": [
                    {
                        "key": "DETECT_ROI_BY_SOURCE.rtmp",
                        "type": "roi_norm",
                        "label": "RTMP 裁切区（归一化 x1,y1,x2,y2）",
                        "hint": "在配置页画框；千问仍看全图。保存后重启 Worker。",
                        "restart": "worker",
                    },
                ],
            },
            {
                "id": "slicer_nms",
                "title": "切片与 NMS",
                "fields": [
                    {"key": "SLICER_SIZE", "type": "integer", "label": "切片边长", "restart": "worker"},
                    {
                        "key": "SLICER_OVERLAP_RATIO",
                        "type": "number",
                        "label": "切片重叠比",
                        "min": 0,
                        "max": 0.9,
                        "step": 0.05,
                        "restart": "worker",
                    },
                    {
                        "key": "GLOBAL_CLASS_AGNOSTIC_NMS_IOU",
                        "type": "number",
                        "label": "NMS IoU",
                        "restart": "worker",
                        "tier": "advanced",
                    },
                    {
                        "key": "GLOBAL_CLASS_AGNOSTIC_NMS_IOF",
                        "type": "number",
                        "label": "NMS IoF",
                        "restart": "worker",
                        "tier": "advanced",
                    },
                ],
            },
            {
                "id": "vlm",
                "title": "千问复核",
                "fields": [
                    {
                        "key": "CLASSES_TO_FIND",
                        "type": "csv",
                        "label": "复核目标类（逗号分隔，如 fishing,swimming）",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_PROMPT_TEMPLATE",
                        "type": "textarea",
                        "label": "Prompt 全文",
                        "hint": "留空且未选冻词时由 pipeline 按 CLASSES_TO_FIND 生成",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_MAX_NEW_TOKENS",
                        "type": "integer",
                        "label": "最大生成 token",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_CONTEXT_MARGIN_MIN",
                        "type": "integer",
                        "label": "上下文边距下限（像素）",
                        "tier": "advanced",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_CONTEXT_MARGIN_RATIO",
                        "type": "number",
                        "label": "上下文边距比例",
                        "tier": "advanced",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_LAYOUT_BY_SOURCE.file",
                        "type": "select",
                        "label": "成片 layout",
                        "options": ["roi_frame", "full_frame", "per_box"],
                        "maps_to": "VLM_LAYOUT_BY_SOURCE",
                        "source": "file",
                        "restart": "worker",
                    },
                    {
                        "key": "VLM_LAYOUT_BY_SOURCE.rtmp",
                        "type": "select",
                        "label": "RTMP layout",
                        "options": ["roi_frame", "full_frame", "per_box"],
                        "maps_to": "VLM_LAYOUT_BY_SOURCE",
                        "source": "rtmp",
                        "restart": "worker",
                    },
                    {
                        "key": "QWEN_DIR_PATH",
                        "type": "qwen_vl_preset",
                        "label": "千问 VL 权重（GPU 复核）",
                        "restart": "worker",
                    },
                ],
            },
        ],
        "ingest_api": {
            "note": "抽帧不在 runtime_config，走 pra.ingest",
            "fields": [
                {"key": "ingest.rtmp_frame_interval_sec", "type": "number", "env": "UVA_FRAME_INTERVAL_S"},
                {"key": "ingest.rtmp_mode", "type": "select"},
                {"key": "ingest.rtmp_custom_pull_url", "type": "string"},
            ],
        },
        "push_api": {
            "fields": [
                {"key": "push.ims_enabled", "type": "boolean"},
                {"key": "push.feiliu_enabled", "type": "boolean"},
                {"key": "push.feiliu_mode", "type": "select", "options": ["off", "record_only", "live"]},
                {"key": "push.feiliu_url", "type": "string"},
                {"key": "push.feiliu_nest_id", "type": "string"},
                {"key": "push.alert_type_to_algo_id", "type": "json_object"},
            ],
        },
    }


def effective_runtime_defaults() -> dict[str, Any]:
    from uva.kernel import runtime_config

    cfg = runtime_config(None)
    # 仅返回工作台会编辑的子集 + 当前默认 prompt 长度提示
    keys = [
        "YOLO_CLASSES",
        "CLASSES_TO_FIND",
        "SLICER_SIZE",
        "SLICER_OVERLAP_RATIO",
        "YOLO_CONF_THRESHOLD",
        "YOLO_CLASS_CONF_THRESHOLD",
        "GLOBAL_CLASS_AGNOSTIC_NMS_IOU",
        "GLOBAL_CLASS_AGNOSTIC_NMS_IOF",
        "VLM_MAX_NEW_TOKENS",
        "VLM_CONTEXT_MARGIN_MIN",
        "VLM_CONTEXT_MARGIN_RATIO",
        "VLM_LAYOUT_BY_SOURCE",
        "DETECT_ROI_BY_SOURCE",
        "YOLO_WEIGHTS_PATH",
        "QWEN_DIR_PATH",
    ]
    out = {k: cfg[k] for k in keys if k in cfg}
    prompt = cfg.get("VLM_PROMPT_TEMPLATE") or ""
    out["VLM_PROMPT_TEMPLATE"] = prompt
    out["_prompt_chars"] = len(prompt)
    return out
