from fastapi.testclient import TestClient

from uva.audit_app import create_app
from uva.contract import Job
from uva.settings import load_settings
from uva.store import Store


def test_audit_lists_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(tmp_path))
    settings = load_settings()
    store = Store(settings.db_path)
    store.enqueue(
        Job(
            job_id="job_a",
            run_id="run_a",
            source_type="file",
            media_path="x.jpg",
            captured_at="2026-09-03T00:00:00Z",
        )
    )
    app = create_app()
    client = TestClient(app)
    runs = client.get("/api/runs").json()
    assert any(r["run_id"] == "run_a" for group in runs["dates"] for r in group["runs"])
    html = client.get("/")
    assert html.status_code == 200
    assert "技术审计" in html.text
    assert "原始 JSON" in html.text
    assert "boxOverlayLabel" in html.text
    assert "lightbox" in html.text
    assert "点击放大" in html.text
