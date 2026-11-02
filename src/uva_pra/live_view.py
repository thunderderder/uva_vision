"""直播预览：用最新 RTMP 抽帧 + 最近一帧推理结果（非完整 RTMP 解码播放器）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uva.audit_view import project_job
from uva.settings import Settings
from uva.store import Store


def _newest_jpeg(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def newest_rtmp_watch_frame(frames_dir: Path) -> Path | None:
    watch = list(frames_dir.glob("**/rtmp_watch/*.jpg"))
    if watch:
        return _newest_jpeg(watch)
    fallback = list(frames_dir.glob("run_*/rtmp_*.jpg"))
    return _newest_jpeg(fallback)


def latest_rtmp_job_row(store: Store) -> dict[str, Any] | None:
    import json

    cur = store._conn.execute(
        """
        SELECT job_id, run_id, status, payload_json, created_at
        FROM jobs
        WHERE source_type = 'rtmp'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    job = json.loads(row[3])
    return {
        "job_id": row[0],
        "run_id": row[1],
        "status": row[2],
        "created_at": row[4],
        "media_path": job.get("media_path"),
        "source_type": job.get("source_type", "rtmp"),
        "captured_at": job.get("captured_at"),
        "job": job,
        "result": store.get_result(row[0]),
    }


def build_live_status(settings: Settings, store: Store) -> dict[str, Any]:
    raw = newest_rtmp_watch_frame(settings.frames_dir)
    job_payload = latest_rtmp_job_row(store)
    yolo_path: str | None = None
    boxes: list[dict[str, Any]] = []
    run_id: str | None = None
    job_id: str | None = None
    outcome: str | None = None

    if job_payload:
        run_id = job_payload.get("run_id")
        job_id = job_payload.get("job_id")
        events = store.list_events(run_id) if run_id else []
        projected = project_job(job_payload, events)
        yolo_path = projected.get("image_path") or media
        boxes = projected.get("boxes") or []
        outcome = projected.get("outcome")

    raw_mtime = raw.stat().st_mtime if raw else None
    return {
        "mode": "snapshot",
        "note": "当前为抽帧刷新预览，不是浏览器内 RTMP 硬解；ingest-rtmp 运行时会自动更新。",
        "raw_frame": str(raw) if raw else None,
        "raw_updated_at": raw_mtime,
        "yolo_frame": yolo_path,
        "boxes": boxes,
        "run_id": run_id,
        "job_id": job_id,
        "outcome": outcome,
        "ingest_hint": raw is not None,
    }
