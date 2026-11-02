"""把 Job/Result/事件收成审计页能直接读的列表，不把 JSON 当主界面。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from uva.p1 import VLM_VERDICT_LABEL, classify_vlm_type, normalize_vlm_verdict
from uva.store import Store

BEIJING = timezone(timedelta(hours=8))

SOURCE_LABEL = {
    "rtmp": "模拟RTMP",
    "file": "文件",
}

SKIP_LABEL = {
    "no_person": "未检出人",
    "not_alert": "有人，未确认预警",
    "yolo_only": "只跑了 YOLO",
    "cooldown": "冷却跳过",
}

QWEN_LABEL = {
    **VLM_VERDICT_LABEL,
    "unknown": "未判定",
}

STATUS_LABEL = {
    "queued": "排队",
    "running": "推理中",
    "done": "完成",
    "failed": "失败",
    "ims_retry": "IMS 待重试",
}


def parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def beijing_parts(ts: str | None) -> tuple[str, str]:
    dt = parse_utc(ts)
    if dt is None:
        return "", ""
    local = dt.astimezone(BEIJING)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _qwen_type(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    objs = item.get("verified_objects") or []
    if objs:
        raw = objs[0].get("type")
        if raw:
            return str(raw)
    raw = item.get("type")
    return str(raw) if raw else None


def qwen_label(raw: str | None) -> str:
    if not raw:
        return "未复核"
    verdict = normalize_vlm_verdict(raw)
    if verdict:
        return VLM_VERDICT_LABEL.get(verdict, verdict)
    key = str(raw).strip().lower()
    return QWEN_LABEL.get(key, str(raw))


def _index_by_id(items: list[dict[str, Any]], key: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            out[int(item.get(key, item.get("id")))] = item
        except (TypeError, ValueError):
            continue
    return out


def project_qwen_pass(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") or {}
    boxes = []
    for item in payload.get("qwen") or []:
        q_type = _qwen_type(item)
        boxes.append(
            {
                "id": item.get("detection_id"),
                "qwen_type": q_type,
                "qwen_label": qwen_label(q_type),
                "description": item.get("description") or "",
            }
        )
    _, clock = beijing_parts(event.get("ts"))
    return {
        "ts": event.get("ts"),
        "time": clock,
        "confirmed": payload.get("confirmed") or [],
        "boxes": boxes,
    }


def _yolo_confidence(det: dict[str, Any]) -> float | None:
    conf = det.get("yolo_confidence", det.get("confidence"))
    if isinstance(conf, str):
        return None
    return _as_float(conf)


def project_boxes(
    result: dict[str, Any] | None,
    qwen_passes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result = result or {}
    detections = list(result.get("detections") or [])
    qwen_by_id = _index_by_id(list(result.get("qwen_results") or []), "detection_id")
    alarm_by_id = _index_by_id(list(result.get("alarms") or []), "id")
    if not detections:
        detections = [dict(item) for item in (result.get("alarms") or [])]
    history_by_id: dict[int, list[dict[str, Any]]] = {}
    for passing in qwen_passes or []:
        for box in passing.get("boxes") or []:
            try:
                det_id = int(box.get("id"))
            except (TypeError, ValueError):
                continue
            history_by_id.setdefault(det_id, []).append(
                {
                    "time": passing.get("time"),
                    "ts": passing.get("ts"),
                    "qwen_type": box.get("qwen_type"),
                    "qwen_label": box.get("qwen_label"),
                    "description": box.get("description") or "",
                }
            )
    boxes = []
    for det in detections:
        try:
            det_id = int(det.get("id"))
        except (TypeError, ValueError):
            continue
        qwen_item = qwen_by_id.get(det_id)
        alarm = alarm_by_id.get(det_id)
        q_type = _qwen_type(qwen_item) or (alarm.get("type") if alarm else None)
        bbox = det.get("global_bbox") or det.get("bbox") or (alarm or {}).get("global_bbox")
        history = history_by_id.get(det_id) or []
        flipped = len({str(h.get("qwen_type") or "") for h in history}) > 1
        boxes.append(
            {
                "id": det_id,
                "bbox": bbox,
                "yolo_class": det.get("class_name") or det.get("yolo_raw_class") or "person",
                "yolo_confidence": _yolo_confidence(det),
                "qwen_type": q_type,
                "qwen_label": qwen_label(q_type),
                "qwen_description": (qwen_item or {}).get("description") or "",
                "alarm_status": (alarm or {}).get("status"),
                "ims_type": (alarm or {}).get("ims_type"),
                "confirmed": bool((alarm or {}).get("status") == "confirmed_alarm" or classify_vlm_type(q_type)),
                "history": history,
                "flipped": flipped,
            }
        )
    boxes.sort(key=lambda item: item["id"])
    return boxes


def _outcome(status: str, result: dict[str, Any] | None, boxes: list[dict[str, Any]]) -> str:
    if status == "failed":
        return "失败"
    if status in ("queued", "running", "ims_retry"):
        return STATUS_LABEL.get(status, status)
    confirmed = [box["qwen_label"] for box in boxes if box.get("confirmed")]
    if confirmed:
        return "预警：" + "、".join(dict.fromkeys(confirmed))
    if result:
        reason = result.get("skipped_reason")
        if reason:
            return SKIP_LABEL.get(str(reason), str(reason))
    if boxes:
        return "有人，未确认预警"
    return STATUS_LABEL.get(status, status or "完成")


def _push_items_summary(
    push: dict[str, Any] | None,
    *,
    ok_prefix: str,
    dry_label: str,
    none_label: str,
    fail_label: str,
) -> tuple[str, str]:
    """返回 (展示文案, chip 语气: ok|warn|bad|muted)。"""
    if not push:
        return none_label, "muted"
    if push.get("status") == "failed":
        return fail_label, "bad"
    items = push.get("items") or []
    ok = sum(1 for i in items if i.get("status") == "ok")
    dry = sum(1 for i in items if i.get("status") in ("dry_run", "record_only"))
    dup = sum(1 for i in items if i.get("status") == "duplicate")
    failed = sum(1 for i in items if i.get("status") == "failed")
    if ok:
        return f"{ok_prefix}（{ok}）", "ok"
    if failed:
        return fail_label, "bad"
    if dry:
        return f"{dry_label}（演练落盘 {dry}）", "muted"
    if dup:
        return f"{dry_label}（重复 {dup}）", "muted"
    if push.get("status") == "ok":
        return none_label, "muted"
    return str(push.get("status") or none_label), "muted"


def _ims_label(result: dict[str, Any] | None) -> str:
    text, _ = _push_items_summary(
        (result or {}).get("ims_push"),
        ok_prefix="已推 IMS",
        dry_label="未推 IMS",
        none_label="未推 IMS",
        fail_label="IMS 失败",
    )
    return text


def _feiliu_items_from_events(events: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("kind") != "feiliu_push" or ev.get("job_id") != job_id:
            continue
        payload = ev.get("payload") or {}
        if isinstance(payload, dict):
            items.append(payload)
    return items


# 飞流 HTTP 预警状态码（与 feiliu.py / 对接方返回 code 对齐）
FEILIU_API_CODES: dict[str, str] = {
    "200": "操作成功",
    "999": "失败",
    "500": "错误",
    "404": "未知资源",
    "401": "无权限",
}


def _normalize_feiliu_code(code: Any) -> str | None:
    if code is None or isinstance(code, bool):
        return None
    if isinstance(code, int):
        return str(code)
    if isinstance(code, float) and code == int(code):
        return str(int(code))
    text = str(code).strip()
    if not text:
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            pass
    return text


def _feiliu_code_label(code: str) -> str:
    desc = FEILIU_API_CODES.get(code)
    return f"{code} {desc}" if desc else code


def _resolve_feiliu_push(
    result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str
) -> dict[str, Any] | None:
    push = (result or {}).get("feiliu_push")
    if not push:
        legacy = _feiliu_items_from_events(events, job_id)
        if legacy:
            push = {"status": "ok", "items": legacy}
    return push if isinstance(push, dict) else None


def _feiliu_item_response(item: dict[str, Any]) -> dict[str, Any] | None:
    resp = item.get("response")
    if isinstance(resp, dict):
        return resp
    return None


def _feiliu_display(
    result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str
) -> tuple[str, str, str]:
    """返回 (单元格文案, chip 语气, 悬停详情)。"""
    push = _resolve_feiliu_push(result, events, job_id)
    tip_lines: list[str] = []
    if not push:
        return "未推", "muted", ""

    items = push.get("items") or []
    record_only = sum(1 for i in items if i.get("status") in ("record_only", "dry_run"))
    duplicate = sum(1 for i in items if i.get("status") == "duplicate")
    if record_only:
        tip_lines.append(f"演练落盘 {record_only} 条（未真 POST 飞流）")
    if duplicate:
        tip_lines.append(f"幂等跳过 {duplicate} 条（本桶已推过）")

    outcome_labels: list[str] = []
    codes: list[str] = []
    for item in items:
        st = item.get("status")
        resp = _feiliu_item_response(item)
        if st == "ok" and resp is not None:
            code = _normalize_feiliu_code(resp.get("code"))
            message = str(resp.get("message") or "").strip()
            if code:
                codes.append(code)
                outcome_labels.append(_feiliu_code_label(code))
                line = f"code {code}"
                if message:
                    line += f"：{message}"
                tip_lines.append(line)
                data = resp.get("data")
                if data not in (None, {}, []):
                    tip_lines.append("data " + json.dumps(data, ensure_ascii=False)[:400])
            elif message:
                outcome_labels.append("已推")
                tip_lines.append(message)
        elif st == "ok" and resp is None:
            outcome_labels.append("已推")
            tip_lines.append("已推飞流（无 HTTP 响应存档）")
        elif st == "failed":
            resp = _feiliu_item_response(item) or {}
            code = _normalize_feiliu_code(resp.get("code"))
            message = str(resp.get("message") or item.get("error") or "").strip()
            if code:
                codes.append(code)
                outcome_labels.append(_feiliu_code_label(code))
                line = f"code {code}"
                if message:
                    line += f"：{message}"
                tip_lines.append(line)
            elif message:
                if "timed out" in message.lower():
                    outcome_labels.append("超时")
                else:
                    outcome_labels.append("失败")
                tip_lines.append(f"失败：{message}")
            else:
                outcome_labels.append("失败")
                tip_lines.append("飞流推送失败")

    if not outcome_labels:
        tooltip = "\n".join(tip_lines)
        if record_only:
            return f"演练落盘（{record_only}）", "warn", tooltip
        if duplicate:
            return f"幂等跳过（{duplicate}）", "muted", tooltip
        return "未推", "muted", tooltip

    unique = list(dict.fromkeys(outcome_labels))
    label = unique[0] if len(unique) == 1 else "、".join(unique)

    if any(c not in ("200",) for c in codes):
        tone = "bad"
    elif codes and all(c == "200" for c in codes):
        tone = "ok"
    elif any(lbl == "已推" for lbl in unique):
        tone = "ok"
    elif any(lbl == "失败" for lbl in unique):
        tone = "bad"
    else:
        tone = "muted"

    tooltip = "\n".join(tip_lines)
    return label, tone, tooltip


def _feiliu_label(result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str) -> str:
    return _feiliu_display(result, events, job_id)[0]


def _ims_chip_tone(result: dict[str, Any] | None) -> str:
    _, tone = _push_items_summary(
        (result or {}).get("ims_push"),
        ok_prefix="已推 IMS",
        dry_label="未推 IMS",
        none_label="未推 IMS",
        fail_label="IMS 失败",
    )
    return tone


def _feiliu_chip_tone(result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str) -> str:
    return _feiliu_display(result, events, job_id)[1]


def _feiliu_tooltip(result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str) -> str:
    return _feiliu_display(result, events, job_id)[2]


def _feiliu_push_logs(result: dict[str, Any] | None, events: list[dict[str, Any]], job_id: str) -> list[dict[str, Any]]:
    push = _resolve_feiliu_push(result, events, job_id)
    if not push:
        return []
    logs: list[dict[str, Any]] = []
    for item in push.get("items") or []:
        if not isinstance(item, dict):
            continue
        preview = item.get("body_preview") if isinstance(item.get("body_preview"), dict) else {}
        logs.append(
            {
                "status": item.get("status"),
                "error": item.get("error"),
                "error_type": item.get("error_type"),
                "log_path": item.get("log_path") or item.get("path"),
                "attempts": item.get("attempts") or [],
                "response": item.get("response"),
                "body_preview": preview,
                "idempotency_key": item.get("idempotency_key"),
            }
        )
    return logs


def project_job(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    job = row.get("job") or {}
    result = row.get("result")
    vlm_events = [ev for ev in events if ev.get("kind") == "vlm" and ev.get("job_id") == row["job_id"]]
    qwen_passes = [project_qwen_pass(ev) for ev in vlm_events]
    boxes = project_boxes(result, qwen_passes)
    evidence = (result or {}).get("evidence") or {}
    image = evidence.get("original") or row.get("media_path")
    date, clock = beijing_parts(row.get("captured_at") or row.get("created_at"))
    name = Path(row.get("media_path") or "").name
    frame_index = job.get("frame_index")
    if frame_index is not None:
        title = f"第 {int(frame_index) + 1} 帧"
        if name:
            title = f"{title} · {name}"
    else:
        title = name or row["job_id"]
    return {
        "job_id": row["job_id"],
        "run_id": row["run_id"],
        "source_type": row["source_type"],
        "source_label": SOURCE_LABEL.get(row["source_type"], row["source_type"]),
        "status": row["status"],
        "status_label": STATUS_LABEL.get(row["status"], row["status"]),
        "title": title,
        "file_name": name,
        "date": date,
        "time": clock,
        "person_count": len(boxes),
        "outcome": _outcome(row["status"], result, boxes),
        "ims_label": _ims_label(result),
        "ims_chip_tone": _ims_chip_tone(result),
        "feiliu_label": _feiliu_label(result, events, row["job_id"]),
        "feiliu_chip_tone": _feiliu_chip_tone(result, events, row["job_id"]),
        "feiliu_tooltip": _feiliu_tooltip(result, events, row["job_id"]),
        "feiliu_push_logs": _feiliu_push_logs(result, events, row["job_id"]),
        "image_path": image,
        "detected_path": evidence.get("detected"),
        "boxes": boxes,
        "qwen_passes": qwen_passes,
        "raw": {"job": job, "result": result},
    }


def _run_card(run_id: str, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    started = min((j.get("created_at") or "") for j in jobs)
    date, clock = beijing_parts(started)
    sources = list(dict.fromkeys(j["source_type"] for j in jobs))
    done = sum(1 for j in jobs if j["status"] == "done")
    failed = sum(1 for j in jobs if j["status"] == "failed")
    people = 0
    alerts = 0
    for job in jobs:
        result = job.get("result") or {}
        people += len(result.get("detections") or [])
        alerts += len(result.get("confirmed_alerts") or [])
    return {
        "run_id": run_id,
        "date": date,
        "time": clock,
        "started_at": started,
        "source_types": sources,
        "source_label": " / ".join(SOURCE_LABEL.get(s, s) for s in sources) or "任务",
        "job_count": len(jobs),
        "done_count": done,
        "failed_count": failed,
        "person_count": people,
        "alert_count": alerts,
        "summary": f"{len(jobs)} 张 · {people} 人 · {alerts} 预警",
    }


def build_audit_index(store: Store) -> dict[str, Any]:
    rows = store.list_audit_rows()
    by_run: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], []).append(row)
    cards = [_run_card(run_id, jobs) for run_id, jobs in by_run.items()]
    cards.sort(key=lambda item: item.get("started_at") or "", reverse=True)
    dates: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        dates.setdefault(card["date"] or "未知日期", []).append(card)
    grouped = [{"date": date, "runs": runs} for date, runs in dates.items()]
    grouped.sort(key=lambda item: item["date"], reverse=True)
    return {"dates": grouped}


def build_run_detail(store: Store, run_id: str) -> dict[str, Any]:
    rows = store.list_audit_rows(run_id)
    events = store.list_events(run_id)
    jobs = [project_job(row, events) for row in rows]
    card = _run_card(run_id, rows) if rows else {
        "run_id": run_id,
        "date": "",
        "time": "",
        "source_label": "任务",
        "job_count": 0,
        "summary": "0 张",
    }
    return {"run": card, "jobs": jobs}
