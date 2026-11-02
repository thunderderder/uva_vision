"""飞流机库 HTTP 预警（演练短期出站）。"""

from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import urllib.error
import urllib.request

from uva.dedup import alert_bucket
from uva.settings import Settings
from uva.store import Store

from uva.contract import Job
from uva_pra.config import PraConfig, load_pra_config

logger = logging.getLogger(__name__)

# 单次 POST 读响应超时；失败后再重试 1 次（共 2 次）
FEILIU_HTTP_TIMEOUT_S = 75.0
FEILIU_HTTP_MAX_ATTEMPTS = 2


def _idem_key(job: Job, alert: dict[str, Any], grid: int) -> str:
    bucket = alert_bucket(alert["alert_type"], alert, grid)
    return f"feiliu:{job.run_id}:{bucket}"


def _algo_id(cfg: PraConfig, alert: dict[str, Any]) -> str | None:
    ims_type = alert.get("ims_type") or alert.get("alert_type")
    if ims_type and ims_type in cfg.push.alert_type_to_algo_id:
        return str(cfg.push.alert_type_to_algo_id[ims_type])
    mapped = cfg.push.alert_type_to_algo_id
    for key, val in mapped.items():
        if key in str(ims_type or ""):
            return str(val)
    return None


def build_payload(cfg: PraConfig, alert: dict[str, Any], image_path: str) -> dict[str, str]:
    algo = _algo_id(cfg, alert)
    if not algo:
        raise ValueError(f"没有 algoId 映射: {alert.get('ims_type') or alert.get('alert_type')}")
    data = Path(image_path).read_bytes()
    # 协议要求 picData 为图片字节的 Base64 字符串（无 data:image/... 前缀）
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "algoId": algo,
        "NestId": cfg.push.feiliu_nest_id or "",
        "picData": encoded,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_push_log(
    push_dir: Path,
    *,
    meta: dict[str, Any],
    body: dict[str, str],
    status: str,
    attempts: list[dict[str, Any]],
    response: Any = None,
) -> Path:
    push_dir.mkdir(parents=True, exist_ok=True)
    path = push_dir / f"feiliu_{int(time.time() * 1000)}.json"
    envelope: dict[str, Any] = {
        "log_version": 1,
        "logged_at": _utc_now(),
        "status": status,
        "meta": meta,
        "request": body,
        "attempts": attempts,
        "response": response,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "feiliu push log job=%s status=%s path=%s attempts=%s",
        meta.get("job_id"),
        status,
        path,
        len(attempts),
    )
    return path


def send_live(
    url: str,
    body: dict[str, str],
    *,
    timeout: float = FEILIU_HTTP_TIMEOUT_S,
    max_attempts: int = FEILIU_HTTP_MAX_ATTEMPTS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.dumps(body).encode("utf-8")
    attempts: list[dict[str, Any]] = []
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        entry: dict[str, Any] = {
            "attempt": attempt,
            "started_at": _utc_now(),
            "timeout_s": timeout,
            "request_bytes": len(data),
        }
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                try:
                    parsed: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {"raw": raw, "code": resp.status}
            entry["duration_ms"] = int((time.perf_counter() - started) * 1000)
            entry["status"] = "ok"
            entry["response"] = parsed
            attempts.append(entry)
            return parsed, attempts
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            entry["duration_ms"] = int((time.perf_counter() - started) * 1000)
            entry["status"] = "failed"
            entry["error_type"] = type(exc).__name__
            entry["error"] = str(exc)
            attempts.append(entry)
            last_exc = exc
            logger.warning(
                "feiliu POST attempt %s/%s failed: %s",
                attempt,
                max_attempts,
                exc,
            )
            if attempt < max_attempts:
                continue
    assert last_exc is not None
    raise last_exc


def _request_meta(
    *,
    job: Job,
    alert: dict[str, Any],
    image_path: str,
    body: dict[str, str],
    mode: str,
    url: str | None,
) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "run_id": job.run_id,
        "mode": mode,
        "url": url,
        "alert_type": alert.get("alert_type"),
        "ims_type": alert.get("ims_type"),
        "image_path": image_path,
        "image_bytes": Path(image_path).stat().st_size,
        "picData_encoding": "base64",
        "picData_chars": len(body.get("picData") or ""),
        "algoId": body.get("algoId"),
        "NestId": body.get("NestId"),
    }


def push_alert(
    *,
    job: Job,
    alert: dict[str, Any],
    evidence: dict[str, str],
    store: Store,
    settings: Settings,
    cfg: PraConfig | None = None,
) -> dict[str, Any] | None:
    cfg = cfg or load_pra_config()
    if not cfg.push.feiliu_enabled:
        return None
    idem = _idem_key(job, alert, settings.dedup_grid)
    if store.has_ims_key(idem):
        return {"status": "duplicate", "idempotency_key": idem}

    image = evidence.get("detected") or evidence.get("original")
    if not image or not Path(image).is_file():
        raise FileNotFoundError("飞流推送缺少证据图")

    body = build_payload(cfg, alert, image)
    mode = (cfg.push.feiliu_mode or "record_only").lower()
    url = (cfg.push.feiliu_url or "").strip() if mode == "live" else None
    meta = _request_meta(job=job, alert=alert, image_path=image, body=body, mode=mode, url=url or None)
    preview = {"algoId": body["algoId"], "NestId": body["NestId"], "picData_encoding": "base64"}

    if mode == "off":
        return None
    if mode == "record_only":
        record_path = write_push_log(
            settings.push_log_dir,
            meta=meta,
            body=body,
            status="record_only",
            attempts=[],
            response={"note": "未 POST，仅落盘供联调核对"},
        )
        store.save_ims_push(idem, job.run_id, job.job_id, "feiliu_record", {"path": str(record_path)})
        return {
            "status": "record_only",
            "path": str(record_path),
            "log_path": str(record_path),
            "body_preview": preview,
            "attempts": [],
        }

    if not url:
        raise ValueError("feiliu_mode=live 需要 feiliu_url")

    attempts: list[dict[str, Any]] = []
    try:
        resp, attempts = send_live(url, body)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        record_path = write_push_log(
            settings.push_log_dir,
            meta=meta,
            body=body,
            status="failed",
            attempts=attempts,
            response={"error": str(exc), "error_type": type(exc).__name__},
        )
        return {
            "status": "failed",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "log_path": str(record_path),
            "body_preview": preview,
            "attempts": attempts,
            "idempotency_key": idem,
        }
    ok = str(resp.get("code")) in ("200", "200.0")
    status = "ok" if ok else "failed"
    record_path = write_push_log(
        settings.push_log_dir,
        meta=meta,
        body=body,
        status=status,
        attempts=attempts,
        response=resp,
    )
    store.save_ims_push(idem, job.run_id, job.job_id, f"feiliu_{status}", resp)
    out: dict[str, Any] = {
        "status": status,
        "response": resp,
        "idempotency_key": idem,
        "log_path": str(record_path),
        "body_preview": preview,
        "attempts": attempts,
    }
    if not ok:
        out["error"] = str(resp.get("message") or resp)
    return out
