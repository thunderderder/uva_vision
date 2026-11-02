"""GPU worker：拉 Job → infer_frame → 去重冷却 → MCP 上图并写入巡查结果。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from uva.contract import Job
from uva.dedup import alert_bucket, person_bucket, should_skip
from uva.evidence import write_job_evidence
from uva.ims_client import IMSClient
from uva.ims_mcp import ImsMcpWriter, addrow_ok, to_mcp_controls
from uva.ims_push import IDEMPOTENCY_CID, add_url, build_field_query_list, write_push_record
from uva.detect_roi import resolve_detect_roi_norm
from uva.kernel import infer_frame, load_models, read_rgb, resolve_vlm_layout, runtime_config
from uva.settings import Settings, load_settings
from uva.store import Store, open_store

logger = logging.getLogger(__name__)


def _load_worker_runtime(runtime_overrides: dict | None) -> dict[str, Any]:
    """pra worker 每帧重读 pra_runtime.yaml，避免改 ROI/阈值后必须手动重启进程。"""
    try:
        from uva_pra.config import load_pra_config, runtime_overrides_for_uva

        return runtime_config(runtime_overrides_for_uva(load_pra_config()))
    except Exception:
        return runtime_config(runtime_overrides)


def _attach_evidence(
    job: Job,
    rgb: Any,
    cfg: dict[str, Any],
    settings: Settings,
    result: dict[str, Any],
    boxes: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    roi_norm = resolve_detect_roi_norm(job.source_type, cfg)
    draw_roi = bool(cfg.get("DRAW_DETECT_ROI_ON_EVIDENCE", True))
    if not roi_norm and not boxes:
        return result
    ev = write_job_evidence(
        settings.evidence_dir,
        job.job_id,
        rgb,
        boxes or [],
        roi_norm=roi_norm,
        draw_detect_roi=draw_roi,
    )
    out = dict(result)
    out["evidence"] = ev
    return out


def make_ims_client(settings: Settings) -> IMSClient:
    return IMSClient(
        auth_url=settings.data_api_auth_url,
        username=settings.data_api_username,
        password=settings.data_api_password,
        aes_key=settings.data_api_aes_key,
        oss_ak=settings.oss_ak,
        oss_sk=settings.oss_sk,
        oss_endpoint=settings.oss_endpoint,
        oss_bucket=settings.oss_bucket,
        env_path=settings.env_path,
    )


def make_mcp_writer(settings: Settings) -> ImsMcpWriter:
    return ImsMcpWriter(
        url=settings.ims_mcp_url,
        secret=settings.ims_mcp_secret,
        sys_id=settings.ims_sys_id,
        form_id=settings.ims_form_id,
    )


def _push_alert(
    *,
    job: Job,
    alert: dict[str, Any],
    evidence: dict[str, str],
    settings: Settings,
    store: Store,
    writer: ImsMcpWriter | None,
    client: IMSClient | None,
    push_ims: bool,
) -> dict[str, Any]:
    bucket = alert_bucket(alert["alert_type"], alert, settings.dedup_grid)
    idem = f"{job.run_id}:{bucket}"
    if store.has_ims_key(idem):
        return {"status": "duplicate", "idempotency_key": idem}

    detected_url = original_url = None
    channel = "mcp" if writer else "rest" if client else "off"
    if push_ims and writer:
        original_url = writer.upload_file(
            evidence["original"],
            f"{job.run_id}_{job.job_id}_original.jpg",
        )
        detected_url = writer.upload_file(
            evidence["detected"],
            f"{job.run_id}_{job.job_id}_detected.jpg",
        )
    elif push_ims and client:
        existing = client.page_by_idempotency(settings.ims_form_id, IDEMPOTENCY_CID, idem)
        if existing:
            store.save_ims_push(idem, job.run_id, job.job_id, "ok", {"existing": True})
            return {"status": "duplicate", "idempotency_key": idem, "ims": "already"}
        original_url = client.upload_file(
            evidence["original"],
            oss_key=f"ims/sys/{settings.ims_sys_id}/uva/{job.run_id}/{job.job_id}_original.jpg",
        )
        detected_url = client.upload_file(
            evidence["detected"],
            oss_key=f"ims/sys/{settings.ims_sys_id}/uva/{job.run_id}/{job.job_id}_detected.jpg",
        )
        if not original_url or not detected_url:
            raise RuntimeError("OSS 上传失败，中止 IMS 推送")

    items = build_field_query_list(
        job=job,
        alert=alert,
        idempotency_key=idem,
        detected_url=detected_url,
        original_url=original_url,
        water_name=settings.water_name or None,
    )
    payload = {"fieldQueryList": items, "controls": to_mcp_controls(items)}
    record_path = write_push_record(settings.push_log_dir, payload)
    if not push_ims or (writer is None and client is None):
        store.save_ims_push(idem, job.run_id, job.job_id, "dry_run", payload)
        return {"status": "dry_run", "idempotency_key": idem, "payload_path": str(record_path), "channel": channel}

    if writer:
        resp = writer.add_row(payload["controls"])
        ok = addrow_ok(resp)
    else:
        assert client is not None
        resp = client.add_row(add_url(settings), payload["fieldQueryList"])
        ok = isinstance(resp, dict) and resp.get("code") in (200, "200")
    status = "ok" if ok else "failed"
    store.save_ims_push(idem, job.run_id, job.job_id, status, resp)
    if status != "ok":
        raise RuntimeError(f"IMS 新增失败: {resp}")
    return {
        "status": status,
        "idempotency_key": idem,
        "response": resp,
        "payload_path": str(record_path),
        "channel": channel,
    }


def _evidence_ready(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    original = evidence.get("original")
    detected = evidence.get("detected")
    return bool(original and detected and Path(original).is_file() and Path(detected).is_file())


def _push_saved_alerts(
    job: Job,
    existing: dict[str, Any],
    *,
    store: Store,
    settings: Settings,
    writer: ImsMcpWriter | None,
    client: IMSClient | None,
    push_ims: bool,
) -> dict[str, Any]:
    evidence = existing.get("evidence") or {}
    pushes = []
    for alert in existing.get("confirmed_alerts") or []:
        store.touch_dedup(
            alert_bucket(alert["alert_type"], alert, settings.dedup_grid),
            time.time(),
            job.job_id,
            alert["alert_type"],
        )
        try:
            push = _push_alert(
                job=job,
                alert=alert,
                evidence=evidence,
                settings=settings,
                store=store,
                writer=writer,
                client=client,
                push_ims=push_ims,
            )
            pushes.append(push)
            store.add_event("ims_push", run_id=job.run_id, job_id=job.job_id, payload=push)
        except Exception as exc:
            logger.exception("IMS push failed")
            store.add_event("ims_retry", run_id=job.run_id, job_id=job.job_id, payload={"error": str(exc)})
            existing = dict(existing)
            existing["ims_push"] = {"status": "failed", "error": str(exc), "done": pushes}
            store.save_result(job.job_id, job.run_id, existing)
            store.set_status(job.job_id, "ims_retry")
            return existing
    existing = dict(existing)
    existing["ims_push"] = {"status": "ok", "items": pushes}
    store.save_result(job.job_id, job.run_id, existing)
    store.set_status(job.job_id, "done")
    return existing


def process_job(
    job: Job,
    *,
    store: Store,
    settings: Settings,
    models,
    cfg: dict[str, Any],
    writer: ImsMcpWriter | None,
    client: IMSClient | None,
    push_ims: bool,
    use_vlm: bool,
) -> dict[str, Any]:
    existing = store.get_result(job.job_id)
    if existing and existing.get("confirmed_alerts") and _evidence_ready(existing.get("evidence")):
        logger.info("ims_retry 只重推 job=%s", job.job_id)
        return _push_saved_alerts(
            job,
            existing,
            store=store,
            settings=settings,
            writer=writer,
            client=client,
            push_ims=push_ims,
        )

    now = time.time()
    rgb = read_rgb(job.media_path)
    roi_norm = resolve_detect_roi_norm(job.source_type, cfg)
    yolo_only = infer_frame(
        rgb,
        cfg,
        models,
        use_vlm=False,
        person_only=True,
        job_id=job.job_id,
        run_id=job.run_id,
        source_type=job.source_type,
    )
    store.add_event(
        "yolo",
        run_id=job.run_id,
        job_id=job.job_id,
        payload={
            "n": len(yolo_only.detections),
            "boxes": yolo_only.detections,
            "detect_roi_norm": roi_norm,
            "source_type": job.source_type,
            "yolo_ms": yolo_only.yolo_ms,
            "yolo_detect_mode": yolo_only.yolo_detect_mode,
        },
    )
    if not yolo_only.detections:
        result = _attach_evidence(job, rgb, cfg, settings, yolo_only.to_dict(), None)
        store.save_result(job.job_id, job.run_id, result)
        store.set_status(job.job_id, "done")
        return result

    need_vlm: list[int] = []
    skipped: list[dict[str, Any]] = []
    for det in yolo_only.detections:
        bucket = person_bucket(det, settings.dedup_grid)
        if should_skip(store, bucket, now, settings.cooldown_s):
            skipped.append({"id": det["id"], "bucket": bucket, "reason": "cooldown"})
            continue
        need_vlm.append(int(det["id"]))
        store.touch_dedup(bucket, now, job.job_id, None)

    if skipped:
        store.add_event("skip_cooldown", run_id=job.run_id, job_id=job.job_id, payload={"skipped": skipped})

    if not need_vlm or not use_vlm:
        result = yolo_only.to_dict()
        result["skipped_reason"] = "cooldown" if skipped and not need_vlm else result.get("skipped_reason")
        result = _attach_evidence(job, rgb, cfg, settings, result, yolo_only.detections)
        store.save_result(job.job_id, job.run_id, result)
        store.set_status(job.job_id, "done")
        return result

    layout = resolve_vlm_layout(job.source_type, cfg)
    framed = infer_frame(
        rgb,
        cfg,
        models,
        use_vlm=True,
        person_only=True,
        job_id=job.job_id,
        run_id=job.run_id,
        detections=yolo_only.detections,
        detection_ids=need_vlm,
        vlm_layout=layout,
        source_type=job.source_type,
    )
    store.add_event(
        "vlm",
        run_id=job.run_id,
        job_id=job.job_id,
        payload={
            "qwen": framed.qwen_results,
            "confirmed": [a.get("ims_type") for a in framed.confirmed_alerts],
            "layout": framed.vlm_layout,
            "vlm_ms": framed.vlm_ms,
            "yolo_ms": framed.yolo_ms,
        },
    )
    framed_dict = _attach_evidence(
        job,
        rgb,
        cfg,
        settings,
        framed.to_dict(),
        framed.confirmed_alerts or framed.detections,
    )
    framed.evidence = framed_dict.get("evidence")
    evidence = framed.evidence or {}
    pushes = []
    feiliu_items: list[dict[str, Any]] = []
    for alert in framed.confirmed_alerts:
        store.touch_dedup(alert_bucket(alert["alert_type"], alert, settings.dedup_grid), now, job.job_id, alert["alert_type"])
        try:
            push = _push_alert(
                job=job,
                alert=alert,
                evidence=evidence,
                settings=settings,
                store=store,
                writer=writer,
                client=client,
                push_ims=push_ims,
            )
            pushes.append(push)
            store.add_event("ims_push", run_id=job.run_id, job_id=job.job_id, payload=push)
            try:
                from uva_pra.hooks import feiliu_after_alert  # type: ignore[import-not-found]

                fl = feiliu_after_alert(
                    job=job,
                    alert=alert,
                    evidence=evidence,
                    store=store,
                    settings=settings,
                )
                if fl is not None:
                    feiliu_items.append(fl)
                    store.add_event("feiliu_push", run_id=job.run_id, job_id=job.job_id, payload=fl)
            except ImportError:
                pass
            except Exception as exc:
                logger.exception("Feiliu push failed")
                failed = {"status": "failed", "error": str(exc)}
                feiliu_items.append(failed)
                store.add_event("feiliu_push", run_id=job.run_id, job_id=job.job_id, payload=failed)
        except Exception as exc:
            logger.exception("IMS push failed")
            store.add_event("ims_retry", run_id=job.run_id, job_id=job.job_id, payload={"error": str(exc)})
            framed.ims_push = {"status": "failed", "error": str(exc), "done": pushes}
            store.save_result(job.job_id, job.run_id, framed.to_dict())
            store.set_status(job.job_id, "ims_retry")
            return framed.to_dict()
    framed.ims_push = {"status": "ok", "items": pushes}
    if feiliu_items:
        framed.feiliu_push = {"status": "ok", "items": feiliu_items}
    result = framed.to_dict()
    store.save_result(job.job_id, job.run_id, result)
    store.set_status(job.job_id, "done")
    return result


def run_worker_loop(
    *,
    once: bool = False,
    until_empty: bool = False,
    push_ims: bool = True,
    use_vlm: bool = True,
    settings: Settings | None = None,
    idle_s: float = 1.0,
    runtime_overrides: dict | None = None,
) -> None:
    settings = settings or load_settings()
    store = open_store(settings)
    stuck = store.requeue_stuck()
    cfg = _load_worker_runtime(runtime_overrides)
    models = load_models(cfg, load_vlm=use_vlm)
    writer = make_mcp_writer(settings) if push_ims and settings.ims_mcp_secret else None
    client = None if writer else (make_ims_client(settings) if push_ims else None)
    if writer:
        writer.ensure_session()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    channel = "mcp" if writer else "rest" if client else "off"
    logger.info(
        "worker 启动 db=%s push_ims=%s channel=%s vlm=%s requeued=%s",
        settings.db_path,
        push_ims,
        channel,
        use_vlm,
        stuck,
    )
    while True:
        job = store.claim_next()
        if job is None:
            if once or until_empty:
                return
            time.sleep(idle_s)
            continue
        try:
            cfg = _load_worker_runtime(runtime_overrides)
            result = process_job(
                job,
                store=store,
                settings=settings,
                models=models,
                cfg=cfg,
                writer=writer,
                client=client,
                push_ims=push_ims,
                use_vlm=use_vlm,
            )
            logger.info(
                "hop gpu_job job=%s run=%s kernel=%s alerts=%s ims=%s",
                job.job_id,
                job.run_id,
                (result or {}).get("status"),
                len((result or {}).get("confirmed_alerts") or []),
                ((result or {}).get("ims_push") or {}).get("status"),
            )
        except Exception as exc:
            logger.exception("job 失败 %s", job.job_id)
            store.add_event("error", run_id=job.run_id, job_id=job.job_id, payload={"error": str(exc)})
            store.set_status(job.job_id, "failed")
        if once:
            return
