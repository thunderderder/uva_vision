"""UVA Vision 工作台 FastAPI：审计画廊 + hops + 配置。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from uva.settings import load_settings
from uva.store import open_store

from uva_pra.bootstrap import PRA_ROOT, ensure_uva_paths
from uva_pra.config import load_pra_config, save_pra_runtime
from uva_pra.device import apply_device_policy

ensure_uva_paths()

WEB_DIR = Path(__file__).resolve().parent / "web" / "static"


class PraConfigPatch(BaseModel):
    device: dict[str, Any] | None = None
    inference: dict[str, Any] | None = None
    ingest: dict[str, Any] | None = None
    runtime: dict[str, Any] | None = None
    push: dict[str, Any] | None = None
    server: dict[str, Any] | None = None


class PraConfigBody(BaseModel):
    patch: PraConfigPatch = Field(default_factory=PraConfigPatch)


class IngestStartBody(BaseModel):
    mode: str | None = None
    run_id: str | None = None
    duration_s: float | None = None
    video_path: str | None = None
    folder_path: str | None = None
    pull_url: str | None = None


class IngestFileBody(BaseModel):
    path: str
    run_id: str | None = None


class WorkerControlBody(BaseModel):
    until_empty: bool = False


class ClearTestDataBody(BaseModel):
    confirm: bool = False


class SaveFrozenPromptBody(BaseModel):
    frozen_id: str
    purpose: str = ""
    overwrite: bool = False
    based_on: str | None = None
    runtime: dict[str, Any] = Field(default_factory=dict)


def _attach_feiliu_log_entries(
    jobs: list[dict[str, Any]],
    *,
    store: Any,
    settings: Any,
) -> None:
    from uva_pra.feiliu_logs import collect_feiliu_log_entries

    for job in jobs:
        jid = job.get("job_id")
        if not jid:
            continue
        raw = job.get("raw") or {}
        result = raw.get("result") if isinstance(raw.get("result"), dict) else store.get_result(jid)
        job["feiliu_log_entries"] = collect_feiliu_log_entries(jid, settings=settings, result=result)


def create_app() -> FastAPI:
    settings = load_settings()
    store = open_store(settings)
    app = FastAPI(title="UVA Vision Workbench", docs_url=None, redoc_url=None)
    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def index(run_id: str | None = None) -> HTMLResponse:
        html = WEB_DIR / "index.html"
        if not html.is_file():
            raise HTTPException(500, "缺少工作台页面")
        body = html.read_text(encoding="utf-8")
        if run_id:
            body = body.replace(
                "</head>",
                f'<script>history.replaceState(null,"","/?run={run_id}");</script></head>',
                1,
            )
        return HTMLResponse(body, headers={"Cache-Control": "no-store"})

    @app.get("/api/runs")
    def api_runs():
        from uva.audit_view import build_audit_index

        return build_audit_index(store)

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str):
        from uva.audit_view import build_run_detail

        detail = build_run_detail(store, run_id)
        job_count = int((detail.get("run") or {}).get("job_count") or 0)
        if not detail["jobs"] and job_count <= 0:
            n = store.count_jobs(run_id)
            if n <= 0:
                raise HTTPException(404, "run 不存在")
            detail["run"]["job_count"] = n
        _attach_feiliu_log_entries(detail.get("jobs") or [], store=store, settings=settings)
        return detail

    def _feiliu_logs_payload(job_id: str) -> dict[str, Any]:
        from uva_pra.feiliu_logs import collect_feiliu_log_entries

        result = store.get_result(job_id)
        logs = collect_feiliu_log_entries(job_id, settings=settings, result=result)
        return {"job_id": job_id, "logs": logs}

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job 不存在")
        return {"job": job.to_dict(), "result": store.get_result(job_id)}

    @app.get("/api/jobs/{job_id}/feiliu-logs")
    @app.get("/api/pra/jobs/{job_id}/feiliu-logs")
    def api_job_feiliu_logs(job_id: str):
        if not job_id or job_id == "undefined":
            raise HTTPException(400, "缺少 job_id")
        return _feiliu_logs_payload(job_id)

    _roi_benchmark_dir = (PRA_ROOT / "fixtures" / "benchmark").resolve()

    @app.get("/api/file")
    def api_file(path: str):
        target = Path(path).resolve()
        allowed = [
            settings.runtime_dir.resolve(),
            settings.evidence_dir.resolve(),
            settings.frames_dir.resolve(),
            settings.push_log_dir.resolve(),
            settings.eval_dir.resolve(),
            _roi_benchmark_dir,
        ]
        if not any(_is_relative_to(target, root) for root in allowed):
            raise HTTPException(403, "路径不在运行时目录")
        if not target.is_file():
            raise HTTPException(404, "文件不存在")
        return FileResponse(target)

    @app.get("/api/hops")
    def api_hops():
        from uva.hops import collect_hops

        return collect_hops(settings)

    @app.get("/api/pra/config")
    def api_pra_config_get():
        cfg = load_pra_config()
        out = cfg.to_dict()
        from uva_pra.runtime_ui import (
            effective_runtime_defaults,
            qwen_vl_presets,
            yolo_weight_presets,
        )

        out["runtime_defaults"] = effective_runtime_defaults()
        out["yolo_weight_presets"] = yolo_weight_presets()
        out["qwen_vl_presets"] = qwen_vl_presets()
        return out

    @app.get("/api/pra/yolo-weight-presets")
    def api_yolo_weight_presets():
        from uva_pra.runtime_ui import yolo_weight_presets

        return {"items": yolo_weight_presets()}

    @app.get("/api/pra/runtime/schema")
    def api_runtime_schema():
        from uva_pra.runtime_ui import runtime_field_schema

        return runtime_field_schema()

    @app.get("/api/pra/frozen-prompts")
    def api_frozen_prompts_list():
        from uva_pra.runtime_ui import list_frozen_prompts

        return {"items": list_frozen_prompts()}

    @app.get("/api/pra/frozen-prompts/{frozen_id}")
    def api_frozen_prompts_get(frozen_id: str):
        from uva_pra.runtime_ui import runtime_from_frozen

        try:
            runtime = runtime_from_frozen(frozen_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"frozen_id": frozen_id, "runtime": runtime}

    @app.post("/api/pra/frozen-prompts")
    def api_frozen_prompts_save(body: SaveFrozenPromptBody):
        from uva_pra.runtime_ui import pra_meta_frozen_key, runtime_from_frozen, save_frozen_prompt

        rt = dict(body.runtime or {})
        prompt = str(rt.get("VLM_PROMPT_TEMPLATE") or "").strip()
        if not prompt:
            raise HTTPException(400, "runtime.VLM_PROMPT_TEMPLATE 不能为空")

        classes = rt.get("CLASSES_TO_FIND") or []
        if isinstance(classes, str):
            classes = [x.strip() for x in classes.split(",") if x.strip()]
        yolo_classes = rt.get("YOLO_CLASSES") or ["person"]
        if isinstance(yolo_classes, str):
            yolo_classes = [x.strip() for x in yolo_classes.split(",") if x.strip()]
        layout = dict(rt.get("VLM_LAYOUT_BY_SOURCE") or {"rtmp": "full_frame", "file": "full_frame"})
        yolo_conf = rt.get("YOLO_CONF_THRESHOLD")
        based_on = body.based_on or rt.get(pra_meta_frozen_key()) or None

        model_refs: dict[str, str] = {}
        if rt.get("YOLO_WEIGHTS_PATH"):
            model_refs["yolo"] = str(rt["YOLO_WEIGHTS_PATH"])
        if rt.get("QWEN_DIR_PATH"):
            model_refs["qwen"] = str(rt["QWEN_DIR_PATH"])

        try:
            saved = save_frozen_prompt(
                body.frozen_id,
                purpose=body.purpose,
                prompt_template=prompt,
                classes_to_find=list(classes),
                yolo_classes=list(yolo_classes),
                layout=layout,
                yolo_conf=float(yolo_conf) if yolo_conf is not None else None,
                based_on=str(based_on) if based_on else None,
                overwrite=bool(body.overwrite),
                model_refs=model_refs or None,
            )
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        frozen_id = saved["frozen_id"]
        runtime = runtime_from_frozen(frozen_id)
        cfg = save_pra_runtime({"runtime": runtime})
        apply_device_policy(cfg)
        return {
            "ok": True,
            "frozen_id": frozen_id,
            "paths": {"json": saved["json_path"], "prompt": saved["prompt_path"]},
            "prompt_sha256": saved["prompt_sha256"],
            "runtime": runtime,
            "note": f"已写入冻词 {frozen_id}，并更新 pra_runtime.yaml 指向该版本。请重启 Worker 使推理生效。",
        }

    @app.put("/api/pra/config")
    def api_pra_config_put(body: PraConfigBody):
        patch = {k: v for k, v in body.patch.model_dump().items() if v is not None}
        cfg = save_pra_runtime(patch)
        apply_device_policy(cfg)
        return {
            "ok": True,
            "config": cfg.to_dict(),
            "note": "已写入 pra_runtime.yaml。ROI/阈值等 runtime 会在 Worker 处理下一帧时自动重载；改 GPU/千问开关或模型路径后请点「重启 Worker」。",
        }

    @app.get("/api/pra/worker/status")
    def api_worker_status():
        from uva_pra.worker_manager import get_worker_manager

        return get_worker_manager().status()

    @app.post("/api/pra/worker/start")
    def api_worker_start(body: WorkerControlBody):
        from uva_pra.worker_manager import get_worker_manager

        try:
            return get_worker_manager().start(until_empty=body.until_empty)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pra/worker/stop")
    def api_worker_stop():
        from uva_pra.worker_manager import get_worker_manager

        return get_worker_manager().stop()

    @app.post("/api/pra/worker/restart")
    def api_worker_restart(body: WorkerControlBody):
        from uva_pra.worker_manager import get_worker_manager

        return get_worker_manager().restart(until_empty=body.until_empty)

    @app.post("/api/pra/runs/new")
    def api_new_run():
        from uva.contract import new_id

        return {"run_id": new_id("run_"), "note": "重测请用新 run_id，勿复用旧 run（幂等去重）"}

    def _clear_test_data_impl(body: ClearTestDataBody) -> dict[str, Any]:
        if not body.confirm:
            raise HTTPException(400, "请传 confirm=true 以确认清空")
        from uva_pra.ingest_manager import get_ingest_manager
        from uva_pra.test_data_reset import clear_local_test_data
        from uva_pra.worker_manager import get_worker_manager

        ingest = get_ingest_manager()
        if ingest.status().get("running"):
            ingest.stop()
        ingest.reset_status()
        worker = get_worker_manager()
        if worker.status().get("running"):
            worker.stop()
        return clear_local_test_data(settings, store)

    @app.post("/api/pra/clear-test-data")
    @app.post("/api/pra/test-data/clear")
    def api_clear_test_data(body: ClearTestDataBody):
        return _clear_test_data_impl(body)

    @app.get("/api/pra/ingest/status")
    def api_ingest_status():
        from uva_pra.ingest_manager import get_ingest_manager

        return get_ingest_manager().status()

    @app.post("/api/pra/ingest/start")
    def api_ingest_start(body: IngestStartBody):
        from uva_pra.ingest_manager import get_ingest_manager

        cfg = load_pra_config()
        mode = body.mode or cfg.ingest.rtmp_mode
        if mode == "image_folder":
            folder_raw = (body.folder_path or cfg.ingest.image_folder_path or "").strip()
            if not folder_raw:
                raise HTTPException(400, "image_folder 模式请填写图片文件夹路径")
            folder = Path(folder_raw).resolve()
            if not folder.is_dir():
                raise HTTPException(404, f"文件夹不存在: {folder}")
            if body.folder_path and body.folder_path.strip():
                save_pra_runtime({"ingest": {"image_folder_path": str(folder)}})
        try:
            return get_ingest_manager().start(
                mode=mode,
                run_id=body.run_id,
                duration_s=body.duration_s,
                video_path=body.video_path,
                folder_path=folder_raw if mode == "image_folder" else body.folder_path,
                pull_url=body.pull_url,
                cfg=cfg,
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/pra/ingest/stop")
    def api_ingest_stop():
        from uva_pra.ingest_manager import get_ingest_manager

        get_ingest_manager().stop()
        return {"ok": True}

    @app.post("/api/pra/ingest/file")
    def api_ingest_file(body: IngestFileBody):
        import os

        from uva.ingest import ingest_path
        from uva.paths import PROJECT_ROOT

        cfg = load_pra_config()
        os.environ["UVA_FRAME_INTERVAL_S"] = str(cfg.ingest.rtmp_frame_interval_sec)
        target = Path(body.path).resolve()
        allowed_roots = [(PROJECT_ROOT / "data").resolve()]
        if not any(_is_relative_to(target, root) for root in allowed_roots):
            raise HTTPException(403, "仅允许 uva/data 下的视频路径")
        if not target.is_file():
            raise HTTPException(404, "文件不存在")
        from uva_pra.worker_manager import get_worker_manager

        get_worker_manager().ensure_running(until_empty=True)
        run_id, jobs = ingest_path(str(target), run_id=body.run_id)
        return {"run_id": run_id, "jobs": len(jobs)}

    @app.get("/api/runs/{run_id}/export")
    def api_run_export(run_id: str, format: str = "json"):
        from uva_pra.export import build_run_export, export_csv

        if format == "csv":
            return PlainTextResponse(export_csv(store, run_id), media_type="text/csv; charset=utf-8")
        return build_run_export(store, run_id)

    @app.get("/api/pra/queue/summary")
    def api_queue_summary():
        run_id = None
        from uva_pra.ingest_manager import get_ingest_manager

        st = get_ingest_manager().status()
        run_id = st.get("run_id")
        if not run_id:
            rows = store.list_audit_rows()
            if rows:
                run_id = rows[-1]["run_id"]
        if not run_id:
            return {"empty": True}
        counts = store._conn.execute(
            """
            select status, count(*) from jobs where run_id=? group by status
            """,
            (run_id,),
        ).fetchall()
        by_status = {str(row[0]): int(row[1]) for row in counts}
        queued = by_status.get("queued", 0)
        return {
            "run_id": run_id,
            "by_status": by_status,
            "needs_worker": queued > 0,
            "hint": "队列有未处理任务；开始收流时会自动启动 Worker，也可在「配置」页手动启动",
        }

    @app.get("/api/pra/roi/sample")
    def api_roi_sample():
        """供配置页画检测 ROI：优先当前 run 最新帧，否则 YOLO 标杆图。"""
        import cv2

        from uva_pra.ingest_manager import get_ingest_manager

        candidates: list[Path] = []
        run_id = get_ingest_manager().status().get("run_id")
        if run_id:
            run_dir = settings.frames_dir / str(run_id)
            if run_dir.is_dir():
                candidates.extend(sorted(run_dir.glob("rtmp_*.jpg"), reverse=True))
        if _roi_benchmark_dir.is_dir():
            candidates.extend(sorted(_roi_benchmark_dir.glob("rtmp_*.jpg"), reverse=True))
        for p in candidates:
            if not p.is_file() or p.stat().st_size < 1024:
                continue
            bgr = cv2.imread(str(p))
            if bgr is None:
                continue
            h, w = bgr.shape[:2]
            return {
                "path": str(p.resolve()),
                "name": p.name,
                "width": w,
                "height": h,
                "run_id": run_id,
            }
        raise HTTPException(404, "没有可用的标杆帧；请先收流或放入 uva_yolo_threshold_exp/fixtures/benchmark")

    @app.get("/api/pra/preview/latest")
    def api_preview_latest():
        from uva.audit_view import build_run_detail
        from uva_pra.ingest_manager import get_ingest_manager

        run_id = get_ingest_manager().status().get("run_id")
        if not run_id:
            rows = store.list_audit_rows()
            if not rows:
                return {"empty": True}
            run_id = rows[0]["run_id"]
        detail = build_run_detail(store, run_id)
        jobs = detail.get("jobs") or []
        if not jobs:
            return {"run_id": run_id, "empty": True}
        job = jobs[-1]
        return {
            "run_id": run_id,
            "job": {
                "job_id": job.get("job_id"),
                "image_path": job.get("image_path"),
                "boxes": job.get("boxes"),
                "outcome": job.get("outcome"),
                "title": job.get("title"),
            },
        }

    return app


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


app = create_app()
