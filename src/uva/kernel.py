"""抽出可 import 的帧推理：YOLO 粗筛 + 可选 Qwen 复核。不改 modules 里的算法。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from uva.contract import FrameResult
from uva.detect_roi import crop_rgb, localize_detections, offset_detections, resolve_detect_roi_norm
from uva.p1 import IMS_TYPE, VLM_TARGET_TYPES, YOLO_CLASSES, classify_vlm_type, is_person_class, sanitize_description
from uva.paths import ensure_pipeline_importable


def _pipeline_config():
    ensure_pipeline_importable()
    import config  # noqa: WPS433  pipeline 同级模块

    return config


def _merge_class_conf_overrides(config, overrides: dict[str, Any]) -> dict[str, float]:
    base = dict(getattr(config, "YOLO_CLASS_CONF_THRESHOLD", {}))
    extra = overrides.get("YOLO_CLASS_CONF_THRESHOLD")
    if isinstance(extra, dict):
        base.update({str(k): float(v) for k, v in extra.items()})
    return base


def runtime_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _pipeline_config()
    overrides = overrides or {}
    yolo_classes = overrides.get("YOLO_CLASSES", getattr(config, "YOLO_CLASSES", YOLO_CLASSES))
    if isinstance(yolo_classes, str):
        yolo_classes = [x.strip() for x in yolo_classes.split(",") if x.strip()]
    vlm_classes = overrides.get("CLASSES_TO_FIND", config.CLASSES_TO_FIND)
    if isinstance(vlm_classes, str):
        vlm_classes = [x.strip() for x in vlm_classes.split(",") if x.strip()]
    if not vlm_classes:
        vlm_classes = list(VLM_TARGET_TYPES)
    return {
        "TEST_IMAGE_PATH": overrides.get("TEST_IMAGE_PATH", config.TEST_IMAGE_PATH),
        "OUTPUT_DIR": overrides.get("OUTPUT_DIR", config.OUTPUT_DIR),
        "YOLO_WEIGHTS_PATH": overrides.get("YOLO_WEIGHTS_PATH", config.YOLO_WEIGHTS_PATH),
        "QWEN_DIR_PATH": overrides.get("QWEN_DIR_PATH", config.QWEN_DIR_PATH),
        "YOLO_CLASSES": list(yolo_classes),
        "CLASSES_TO_FIND": list(vlm_classes),
        "SLICER_SIZE": int(overrides.get("SLICER_SIZE", config.SLICER_SIZE)),
        "SLICER_OVERLAP_RATIO": float(overrides.get("SLICER_OVERLAP_RATIO", config.SLICER_OVERLAP_RATIO)),
        "YOLO_CONF_THRESHOLD": float(overrides.get("YOLO_CONF_THRESHOLD", config.YOLO_CONF_THRESHOLD)),
        "YOLO_CLASS_CONF_THRESHOLD": _merge_class_conf_overrides(config, overrides),
        "GLOBAL_CLASS_AGNOSTIC_NMS_IOU": float(
            overrides.get("GLOBAL_CLASS_AGNOSTIC_NMS_IOU", config.GLOBAL_CLASS_AGNOSTIC_NMS_IOU)
        ),
        "GLOBAL_CLASS_AGNOSTIC_NMS_IOF": float(
            overrides.get("GLOBAL_CLASS_AGNOSTIC_NMS_IOF", config.GLOBAL_CLASS_AGNOSTIC_NMS_IOF)
        ),
        "PROMPT_BOX_COLOR": tuple(overrides.get("PROMPT_BOX_COLOR", config.PROMPT_BOX_COLOR)),
        "PROMPT_BOX_THICKNESS": int(overrides.get("PROMPT_BOX_THICKNESS", config.PROMPT_BOX_THICKNESS)),
        "PROMPT_FONT_SCALE": float(overrides.get("PROMPT_FONT_SCALE", config.PROMPT_FONT_SCALE)),
        "VLM_PROMPT_TEMPLATE": overrides.get(
            "VLM_PROMPT_TEMPLATE",
            config.build_vlm_prompt_template(vlm_classes),
        ),
        "VLM_MAX_NEW_TOKENS": int(overrides.get("VLM_MAX_NEW_TOKENS", config.VLM_MAX_NEW_TOKENS)),
        "VLM_CONTEXT_MARGIN_MIN": int(overrides.get("VLM_CONTEXT_MARGIN_MIN", config.VLM_CONTEXT_MARGIN_MIN)),
        "VLM_CONTEXT_MARGIN_RATIO": float(
            overrides.get("VLM_CONTEXT_MARGIN_RATIO", config.VLM_CONTEXT_MARGIN_RATIO)
        ),
        "VLM_LAYOUT_BY_SOURCE": dict(
            overrides.get("VLM_LAYOUT_BY_SOURCE", getattr(config, "VLM_LAYOUT_BY_SOURCE", {}))
        ),
        "DETECT_ROI_BY_SOURCE": dict(
            overrides.get("DETECT_ROI_BY_SOURCE", getattr(config, "DETECT_ROI_BY_SOURCE", {}))
        ),
        "YOLO_DETECT_MODE_BY_SOURCE": dict(
            overrides.get(
                "YOLO_DETECT_MODE_BY_SOURCE",
                getattr(config, "YOLO_DETECT_MODE_BY_SOURCE", {}),
            )
        ),
        "YOLO_AUTO_SLICE_MAX_EDGE": int(
            overrides.get("YOLO_AUTO_SLICE_MAX_EDGE", getattr(config, "YOLO_AUTO_SLICE_MAX_EDGE", 1920))
        ),
    }


def resolve_vlm_layout(source_type: str | None, cfg: dict[str, Any] | None = None) -> str:
    """来源未单独配置时用 file 的布局。"""
    cfg = cfg or runtime_config()
    table = cfg.get("VLM_LAYOUT_BY_SOURCE") or {}
    layout = table.get(source_type or "file", table.get("file", "roi_frame"))
    if layout not in {"full_frame", "per_box", "roi_frame"}:
        return "roi_frame"
    return layout


def resolve_yolo_detect_mode(
    source_type: str | None,
    cfg: dict[str, Any],
    rgb_shape: tuple[int, ...],
) -> str:
    """direct / slice；auto 时长边超过 YOLO_AUTO_SLICE_MAX_EDGE 时用 slice（4K 线）。"""
    table = cfg.get("YOLO_DETECT_MODE_BY_SOURCE") or {}
    st = source_type or "file"
    mode = str(table.get(st) or table.get("file") or "auto").lower()
    if mode == "auto":
        h, w = int(rgb_shape[0]), int(rgb_shape[1])
        max_edge = int(cfg.get("YOLO_AUTO_SLICE_MAX_EDGE", 1920))
        return "slice" if max(h, w) > max_edge else "direct"
    if mode in {"direct", "slice"}:
        return mode
    return "slice"


def _run_yolo_on_rgb(rgb, cfg: dict[str, Any], models: LoadedModels, mode: str) -> list[dict[str, Any]]:
    from modules.frame_detect import run_yolo_direct_on_rgb, run_yolo_global_nms_on_rgb

    if mode == "direct":
        return run_yolo_direct_on_rgb(rgb, cfg, models.detector)
    return run_yolo_global_nms_on_rgb(rgb, cfg, models.slicer, models.detector)


def _prepare_vlm_inputs(
    rgb: np.ndarray,
    dets: list[dict[str, Any]],
    layout: str,
    source_type: str | None,
    cfg: dict[str, Any],
) -> tuple[np.ndarray, list[dict[str, Any]], str]:
    """roi_frame → 裁 detect ROI，在局部坐标上走 full_frame 千问。"""
    if layout != "roi_frame":
        return rgb, dets, layout
    roi_norm = resolve_detect_roi_norm(source_type, cfg)
    if not roi_norm:
        return rgb, dets, "full_frame"
    crop, offset = crop_rgb(rgb, roi_norm)
    return crop, localize_detections(dets, offset), "full_frame"


@dataclass
class LoadedModels:
    slicer: Any
    detector: Any
    prompter: Any
    postprocessor: Any
    vlm_verifier: Any | None = None


def load_models(
    cfg: dict[str, Any] | None = None,
    *,
    load_vlm: bool = True,
    load_yolo: bool = True,
) -> LoadedModels:
    ensure_pipeline_importable()
    from modules.postprocessor import Postprocessor
    from modules.visual_prompter import VisualPrompter

    cfg = cfg or runtime_config()
    slicer = None
    detector = None
    if load_yolo:
        from modules.detector import ZeroShotDetector
        from modules.slicer import ImageSlicer

        slicer = ImageSlicer(slice_size=cfg["SLICER_SIZE"], overlap_ratio=cfg["SLICER_OVERLAP_RATIO"])
        detector = ZeroShotDetector(
            cfg["YOLO_WEIGHTS_PATH"],
            cfg["YOLO_CLASSES"],
            conf_threshold=cfg["YOLO_CONF_THRESHOLD"],
            class_conf_threshold=cfg["YOLO_CLASS_CONF_THRESHOLD"],
        )
    prompter = VisualPrompter(
        color=cfg["PROMPT_BOX_COLOR"],
        thickness=cfg["PROMPT_BOX_THICKNESS"],
        font_scale=cfg["PROMPT_FONT_SCALE"],
    )
    postprocessor = Postprocessor(cfg["CLASSES_TO_FIND"])
    vlm = None
    if load_vlm:
        from modules.vlm_verifier import VLMVerifier
        from uva.model_assets import ensure_qwen_vl_dir

        qwen_dir = ensure_qwen_vl_dir(cfg["QWEN_DIR_PATH"], allow_download=False)
        vlm = VLMVerifier(str(qwen_dir))
    return LoadedModels(
        slicer=slicer,
        detector=detector,
        prompter=prompter,
        postprocessor=postprocessor,
        vlm_verifier=vlm,
    )


def _attach_alert_fields(alarms: list[dict[str, Any]], qwen_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    confirmed: list[dict[str, Any]] = []
    for alarm in alarms:
        mapped = classify_vlm_type(alarm.get("type"))
        qwen = qwen_by_id.get(int(alarm["id"]), {})
        desc = sanitize_description(qwen.get("description") or alarm.get("type"), mapped)
        alarm["alert_type"] = mapped
        alarm["ims_type"] = None
        alarm["description"] = desc
        if mapped:
            alarm["status"] = "confirmed_alarm"
            alarm["ims_type"] = IMS_TYPE[mapped]
            alarm["confidence"] = "high"
            confirmed.append(alarm)
        else:
            alarm["status"] = "false_alarm"
            alarm["confidence"] = "low"
    return confirmed


def infer_frame(
    rgb: np.ndarray,
    cfg: dict[str, Any] | None = None,
    models: LoadedModels | None = None,
    *,
    use_vlm: bool = True,
    person_only: bool = True,
    job_id: str | None = None,
    run_id: str | None = None,
    detection_ids: list[int] | None = None,
    vlm_layout: str | None = None,
    detections: list[dict[str, Any]] | None = None,
    source_type: str | None = None,
) -> FrameResult:
    """YOLO（direct 或 slice）+ 可选 Qwen。传入 ``detections`` 时跳过 YOLO（worker 复用框）。

    ``roi_frame`` 布局：在 detect ROI 裁切图上做一次 full_frame 千问。
    """
    ensure_pipeline_importable()
    from modules.vlm_frame_verify import run_vlm_verify

    cfg = cfg or runtime_config()
    if models is None:
        models = load_models(cfg, load_vlm=use_vlm)

    yolo_ms: int | None = None
    vlm_ms: int | None = None
    yolo_mode: str | None = None

    if detections is not None:
        dets = list(detections)
    else:
        yolo_mode = resolve_yolo_detect_mode(source_type, cfg, rgb.shape)
        t0 = time.perf_counter()
        roi_norm = resolve_detect_roi_norm(source_type, cfg)
        if roi_norm:
            crop, offset = crop_rgb(rgb, roi_norm)
            dets = _run_yolo_on_rgb(crop, cfg, models, yolo_mode)
            dets = offset_detections(dets, offset)
        else:
            dets = _run_yolo_on_rgb(rgb, cfg, models, yolo_mode)
        yolo_ms = int((time.perf_counter() - t0) * 1000)

    if person_only:
        dets = [d for d in dets if is_person_class(d.get("class_name"))]
    if detection_ids is not None:
        allow = set(detection_ids)
        dets = [d for d in dets if d.get("id") in allow]

    layout = (
        vlm_layout
        if vlm_layout in {"full_frame", "per_box", "roi_frame"}
        else resolve_vlm_layout(source_type, cfg)
    )

    if not dets:
        return FrameResult(
            job_id=job_id,
            run_id=run_id,
            detections=[],
            qwen_results=[],
            alarms=[],
            confirmed_alerts=[],
            skipped_reason="no_person",
            status="no_targets",
            vlm_layout=layout if use_vlm else None,
            yolo_ms=yolo_ms,
            vlm_ms=None,
            yolo_detect_mode=yolo_mode,
        )

    if not use_vlm:
        return FrameResult(
            job_id=job_id,
            run_id=run_id,
            detections=dets,
            qwen_results=[],
            alarms=[],
            confirmed_alerts=[],
            skipped_reason="yolo_only",
            status="yolo_only",
            yolo_ms=yolo_ms,
            vlm_ms=None,
            yolo_detect_mode=yolo_mode,
        )

    if models.vlm_verifier is None:
        raise RuntimeError("use_vlm=True 但模型未加载 Qwen")

    vlm_rgb, vlm_dets, call_layout = _prepare_vlm_inputs(rgb, dets, layout, source_type, cfg)
    t_vlm = time.perf_counter()
    qwen_results, alarms, scenes = run_vlm_verify(
        vlm_rgb,
        cfg,
        vlm_dets,
        models.prompter,
        models.vlm_verifier,
        models.postprocessor,
        layout=call_layout,
    )
    vlm_ms = int((time.perf_counter() - t_vlm) * 1000)
    qwen_by_id = {int(item["detection_id"]): item for item in qwen_results}
    confirmed = _attach_alert_fields(alarms, qwen_by_id)
    return FrameResult(
        job_id=job_id,
        run_id=run_id,
        detections=dets,
        qwen_results=qwen_results,
        alarms=alarms,
        confirmed_alerts=confirmed,
        scene_descriptions=scenes,
        skipped_reason=None if confirmed else "not_alert",
        status="ok" if confirmed else "no_alert",
        vlm_layout=layout,
        yolo_ms=yolo_ms,
        vlm_ms=vlm_ms,
        yolo_detect_mode=yolo_mode,
    )


def read_rgb(path: str) -> np.ndarray:
    img = cv2.imread(path)
    if img is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def run_still_pipeline(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """兼容原 main.run_pipeline：单图推理并写 JSON 到 OUTPUT_DIR。"""
    import json
    import os

    cfg = runtime_config(overrides)
    os.makedirs(cfg["OUTPUT_DIR"], exist_ok=True)
    rgb = read_rgb(cfg["TEST_IMAGE_PATH"])
    models = load_models(cfg, load_vlm=True)
    result = infer_frame(rgb, cfg, models, use_vlm=True, person_only=True)

    if result.status == "no_targets":
        return {"status": "no_targets", "output_dir": cfg["OUTPUT_DIR"]}

    yolo_json_path = os.path.join(cfg["OUTPUT_DIR"], "yolo_detections.json")
    with open(yolo_json_path, "w", encoding="utf-8") as fh:
        json.dump({"yolo_detections": result.detections}, fh, ensure_ascii=False, indent=4)

    prompted = models.prompter.inject_prompt(rgb, result.detections, bbox_key="global_bbox")
    prompted_img_path = os.path.join(cfg["OUTPUT_DIR"], "full_image_prompted.png")
    cv2.imwrite(prompted_img_path, cv2.cvtColor(prompted, cv2.COLOR_RGB2BGR))

    qwen_json_path = os.path.join(cfg["OUTPUT_DIR"], "qwen_results.json")
    with open(qwen_json_path, "w", encoding="utf-8") as fh:
        json.dump({"qwen_results": result.qwen_results}, fh, ensure_ascii=False, indent=4)

    compare_rows = []
    for alarm in result.alarms:
        yolo_label = str(alarm.get("yolo_raw_class", "")).lower().strip()
        qwen_label = str(alarm.get("type", "")).lower().strip()
        compare_rows.append(
            {
                "id": alarm["id"],
                "slice_idx": alarm.get("slice_idx"),
                "yolo_type": alarm.get("yolo_raw_class"),
                "qwen_type": alarm.get("type"),
                "status": alarm.get("status"),
                "same_label": yolo_label == qwen_label,
                "alert_type": alarm.get("alert_type"),
            }
        )
    compare_json_path = os.path.join(cfg["OUTPUT_DIR"], "yolo_qwen_compare.json")
    with open(compare_json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "total": len(compare_rows),
                "same_label_count": sum(1 for row in compare_rows if row["same_label"]),
                "confirmed_alarm_count": len(result.confirmed_alerts),
                "rows": compare_rows,
            },
            fh,
            ensure_ascii=False,
            indent=4,
        )

    final_json_path = os.path.join(cfg["OUTPUT_DIR"], "final_results.json")
    models.postprocessor.save_json(
        {
            "total_yolo_boxes": len(result.detections),
            "total_confirmed_alarms": len(result.confirmed_alerts),
            "alarms": result.alarms,
            "scene_descriptions": result.scene_descriptions,
        },
        final_json_path,
    )
    return {
        "status": "ok",
        "output_dir": cfg["OUTPUT_DIR"],
        "prompted_image_path": prompted_img_path,
        "yolo_json_path": yolo_json_path,
        "qwen_json_path": qwen_json_path,
        "compare_json_path": compare_json_path,
        "final_json_path": final_json_path,
        "frame_result": result.to_dict(),
    }
