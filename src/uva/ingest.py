"""文件入口：图片或视频抽帧写入同一 Job 队列。"""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2

from uva.contract import Job, Telemetry, new_id, utc_now
from uva.settings import Settings, load_settings
from uva.store import Store, open_store
from uva.video_telemetry import load_cues_for_video, telemetry_at_ms

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".ts"}


def _copy_into_runtime(src: Path, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def ingest_image(
    path: Path,
    *,
    run_id: str,
    store: Store,
    settings: Settings,
    source_type: str = "file",
    frame_index: int | None = None,
    captured_at: str | None = None,
    telemetry: Telemetry | None = None,
) -> Job:
    dest = _copy_into_runtime(path, settings.frames_dir / run_id, path.name)
    job = Job(
        job_id=new_id("job_"),
        run_id=run_id,
        source_type=source_type,  # type: ignore[arg-type]
        media_path=str(dest),
        captured_at=captured_at or utc_now(),
        frame_index=frame_index,
        telemetry=telemetry or Telemetry(water_name=settings.water_name or None),
        water_name=settings.water_name or None,
    )
    store.enqueue(job)
    store.add_event("ingest", run_id=run_id, job_id=job.job_id, payload={"path": str(dest), "source_type": source_type})
    return job


def ingest_video(path: Path, *, run_id: str, store: Store, settings: Settings, interval_s: float | None = None) -> list[Job]:
    interval = interval_s if interval_s is not None else settings.frame_interval_s
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"打不开视频: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    jobs: list[Job] = []
    idx = 0
    t = 0.0
    duration = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / max(fps, 1e-6)
    out_dir = settings.frames_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    cues = load_cues_for_video(path, settings.runtime_dir / "subtitles")
    while t <= duration + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, bgr = cap.read()
        if not ok:
            break
        frame_path = out_dir / f"file_{idx:06d}.jpg"
        cv2.imwrite(str(frame_path), bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        tele = telemetry_at_ms(cues, t * 1000.0, water_name=settings.water_name or None)
        jobs.append(
            ingest_image(
                frame_path,
                run_id=run_id,
                store=store,
                settings=settings,
                source_type="file",
                frame_index=idx,
                captured_at=tele.captured_at_local,
                telemetry=tele,
            )
        )
        idx += 1
        t += interval
    cap.release()
    return jobs


def ingest_folder(
    folder: str | Path,
    *,
    run_id: str | None = None,
    settings: Settings | None = None,
    recursive: bool = True,
) -> tuple[str, list[Job]]:
    """将文件夹内图片依次入队（用于历史抽帧批量重跑 YOLO/VLM）。"""
    settings = settings or load_settings()
    store = open_store(settings)
    run_id = run_id or new_id("run_")
    root = Path(folder).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"不是文件夹: {root}")
    iterator = root.rglob("*") if recursive else root.iterdir()
    paths = sorted(p for p in iterator if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    if not paths:
        raise ValueError(f"文件夹内没有图片（{', '.join(sorted(IMAGE_EXT))}）: {root}")
    jobs: list[Job] = []
    dest_dir = settings.frames_dir / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    for idx, src in enumerate(paths):
        dest_name = f"folder_{idx:06d}__{src.name}"
        dest = _copy_into_runtime(src, dest_dir, dest_name)
        jobs.append(
            ingest_image(
                dest,
                run_id=run_id,
                store=store,
                settings=settings,
                source_type="file",
                frame_index=idx,
            )
        )
    store.add_event(
        "run_start",
        run_id=run_id,
        payload={
            "source": str(root),
            "jobs": len(jobs),
            "kind": "image_folder",
            "recursive": recursive,
        },
    )
    return run_id, jobs


def ingest_path(path: str | Path, *, run_id: str | None = None, settings: Settings | None = None) -> tuple[str, list[Job]]:
    settings = settings or load_settings()
    store = open_store(settings)
    run_id = run_id or new_id("run_")
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(src)
    suffix = src.suffix.lower()
    if suffix in IMAGE_EXT:
        jobs = [ingest_image(src, run_id=run_id, store=store, settings=settings)]
    elif suffix in VIDEO_EXT:
        jobs = ingest_video(src, run_id=run_id, store=store, settings=settings)
    else:
        raise ValueError(f"不支持的文件类型: {suffix}")
    gps_n = sum(1 for job in jobs if job.telemetry.latitude is not None and job.telemetry.longitude is not None)
    store.add_event(
        "run_start",
        run_id=run_id,
        payload={"source": str(src), "jobs": len(jobs), "kind": "file", "gps_frames": gps_n},
    )
    return run_id, jobs
