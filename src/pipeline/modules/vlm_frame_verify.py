"""对单帧 NMS 后的检测列表调用 Qwen-VL（full_frame / roi_frame 一次，per_box 逐框）。"""

from __future__ import annotations

from typing import Any

from modules.context_crop import context_crop_and_local_box


def _int_box(bbox: list | tuple) -> list[int]:
    return [int(round(float(x))) for x in bbox]


def _prompt_dets(global_detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for det in global_detections:
        box = _int_box(det["global_bbox"])
        out.append(
            {
                "id": det["id"],
                "bbox": box,
                "global_bbox": box,
                "class_name": det["class_name"],
                "confidence": det.get("confidence", 0.0),
            }
        )
        if isinstance(det.get("confidence"), (int, float)):
            out[-1]["yolo_confidence"] = float(det["confidence"])
    return out


def _split_qwen_results(
    global_detections: list[dict[str, Any]],
    vlm_results: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id = {
        int(obj["id"]): obj
        for obj in (vlm_results.get("verified_objects") or [])
        if "id" in obj
    }
    raw = vlm_results.get("raw_text", "")
    items: list[dict[str, Any]] = []
    for det in global_detections:
        obj = by_id.get(int(det["id"]))
        chosen = [obj] if obj else []
        desc = (obj or {}).get("description", "") if obj else ""
        items.append(
            {
                "detection_id": det["id"],
                "global_bbox": det["global_bbox"],
                "yolo_class": det["class_name"],
                "verified_objects": chosen,
                "description": desc,
                "raw_text": raw,
            }
        )
    return items


def run_vlm_on_full_frame(
    full_img_rgb,
    cfg: dict[str, Any],
    global_detections: list[dict[str, Any]],
    prompter,
    vlm_verifier,
    postprocessor,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    prompt_dets = _prompt_dets(global_detections)
    prompted = prompter.inject_prompt(full_img_rgb, prompt_dets, bbox_key="global_bbox")
    vlm_results = vlm_verifier.verify(
        prompted,
        cfg["CLASSES_TO_FIND"],
        prompt_dets,
        prompt_template=cfg["VLM_PROMPT_TEMPLATE"],
        max_new_tokens=cfg["VLM_MAX_NEW_TOKENS"],
    )
    qwen_results = _split_qwen_results(global_detections, vlm_results)
    scene_descriptions = [
        f"Target id {item['detection_id']}: {item['description']}" for item in qwen_results
    ]
    final_json = postprocessor.process(prompt_dets, vlm_results)
    alarms = final_json["alarms"]
    for alarm in alarms:
        alarm["slice_idx"] = None
    return qwen_results, alarms, scene_descriptions


def run_vlm_for_each_detection(
    full_img_rgb,
    cfg: dict[str, Any],
    global_detections: list[dict[str, Any]],
    prompter,
    vlm_verifier,
    postprocessor,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    all_qwen_results: list[dict[str, Any]] = []
    all_final_alarms: list[dict[str, Any]] = []
    scene_descriptions: list[str] = []

    for det in global_detections:
        crop, local_bbox = context_crop_and_local_box(
            full_img_rgb,
            det["global_bbox"],
            cfg["VLM_CONTEXT_MARGIN_MIN"],
            cfg["VLM_CONTEXT_MARGIN_RATIO"],
        )
        one_det = [
            {
                "id": det["id"],
                "bbox": local_bbox,
                "global_bbox": det["global_bbox"],
                "class_name": det["class_name"],
                "confidence": det.get("confidence", 0.0),
            }
        ]
        prompted = prompter.inject_prompt(crop, one_det, bbox_key="bbox")
        vlm_results = vlm_verifier.verify(
            prompted,
            cfg["CLASSES_TO_FIND"],
            one_det,
            prompt_template=cfg["VLM_PROMPT_TEMPLATE"],
            max_new_tokens=cfg["VLM_MAX_NEW_TOKENS"],
        )
        objs = vlm_results.get("verified_objects") or []
        matched = next((obj for obj in objs if obj.get("id") == det["id"]), None)
        chosen = [matched] if matched else objs
        desc = (matched or {}).get("description") or vlm_results.get("description", "")
        all_qwen_results.append(
            {
                "detection_id": det["id"],
                "global_bbox": det["global_bbox"],
                "yolo_class": det["class_name"],
                "verified_objects": chosen,
                "description": desc,
                "raw_text": vlm_results.get("raw_text", ""),
            }
        )
        scene_descriptions.append(f"Target id {det['id']}: {desc}")
        final_json = postprocessor.process(one_det, vlm_results)
        for alarm in final_json["alarms"]:
            alarm["slice_idx"] = None
        all_final_alarms.extend(final_json["alarms"])

    return all_qwen_results, all_final_alarms, scene_descriptions


def run_vlm_verify(
    full_img_rgb,
    cfg: dict[str, Any],
    global_detections: list[dict[str, Any]],
    prompter,
    vlm_verifier,
    postprocessor,
    *,
    layout: str = "full_frame",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if layout == "full_frame":
        return run_vlm_on_full_frame(
            full_img_rgb, cfg, global_detections, prompter, vlm_verifier, postprocessor
        )
    return run_vlm_for_each_detection(
        full_img_rgb, cfg, global_detections, prompter, vlm_verifier, postprocessor
    )
