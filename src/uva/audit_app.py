"""本机 127.0.0.1 技术审计页：按 run 看抽帧、YOLO、Qwen、IMS。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from uva.settings import load_settings
from uva.store import open_store

WEB_DIR = Path(__file__).resolve().parent / "web" / "static"


def create_app() -> FastAPI:
    settings = load_settings()
    store = open_store(settings)
    app = FastAPI(title="UVA 技术审计", docs_url=None, redoc_url=None)
    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = WEB_DIR / "index.html"
        if not html.is_file():
            raise HTTPException(500, "缺少审计页")
        return HTMLResponse(html.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @app.get("/api/runs")
    def api_runs():
        from uva.audit_view import build_audit_index

        return build_audit_index(store)

    @app.get("/api/runs/{run_id}")
    def api_run(run_id: str):
        from uva.audit_view import build_run_detail

        detail = build_run_detail(store, run_id)
        if not detail["jobs"]:
            raise HTTPException(404, "run 不存在")
        return detail

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, "job 不存在")
        return {"job": job.to_dict(), "result": store.get_result(job_id)}

    @app.get("/api/file")
    def api_file(path: str):
        target = Path(path).resolve()
        allowed = [
            settings.runtime_dir.resolve(),
            settings.evidence_dir.resolve(),
            settings.frames_dir.resolve(),
            settings.push_log_dir.resolve(),
            settings.eval_dir.resolve(),
        ]
        if not any(_is_relative_to(target, root) for root in allowed):
            raise HTTPException(403, "路径不在运行时目录")
        if not target.is_file():
            raise HTTPException(404, "文件不存在")
        return FileResponse(target)

    return app


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


app = create_app()
