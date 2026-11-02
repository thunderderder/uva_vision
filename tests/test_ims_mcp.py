from pathlib import Path

from uva.contract import Job, Telemetry
from uva.ims_mcp import (
    addrow_ok,
    clean_oss_url,
    extract_presign_url,
    parse_mcp_tool_text,
    to_mcp_controls,
)
from uva.ims_push import FIELDS, build_field_query_list
from uva.p1 import SOURCE_RTMP, VERIFY_PENDING
from uva.settings import load_settings
from uva.store import Store
from uva.worker import _push_alert, process_job


def test_parse_presign_plain_url():
    text = "API Response (Status: 200):\nhttps://example-bucket.oss-example.aliyuncs.com/ims/sys/1/a.jpg?sig=1"
    parsed = parse_mcp_tool_text(text)
    url = extract_presign_url(parsed)
    assert url.startswith("https://")
    assert "sig=1" in url
    assert "?" not in clean_oss_url(url)


def test_parse_json_addrow():
    text = 'API Response (Status: 200):\n{"code":200,"data":"2095","message":"操作成功"}'
    parsed = parse_mcp_tool_text(text)
    assert addrow_ok(parsed)
    assert parsed["data"] == "2095"


def test_to_mcp_controls_uses_cid():
    job = Job(
        job_id="job_1",
        run_id="run_9",
        source_type="rtmp",
        media_path="a.jpg",
        captured_at="2026-09-03T07:00:00Z",
        telemetry=Telemetry(),
    )
    items = build_field_query_list(
        job=job,
        alert={"alert_type": "fishing", "ims_type": "钓鱼人", "description": "人在水边坐"},
        idempotency_key="run_9:fishing:0:0",
        detected_url="https://example-bucket.oss-example.aliyuncs.com/a.jpg?x=1",
        original_url="https://example-bucket.oss-example.aliyuncs.com/b.jpg",
    )
    controls = to_mcp_controls(items)
    assert all("ctrlId" in row and "value" in row and "key" not in row for row in controls)
    by_id = {row["ctrlId"]: row["value"] for row in controls}
    assert by_id[FIELDS["ai_type"]["cId"]] == "钓鱼人"
    assert by_id[FIELDS["source"]["cId"]] == SOURCE_RTMP
    assert by_id[FIELDS["verify"]["cId"]] == VERIFY_PENDING
    assert "?" not in by_id[FIELDS["det_img"]["cId"]]


class _FakeWriter:
    def __init__(self):
        self.uploaded = []
        self.rows = []

    def upload_file(self, local_path, file_name):
        self.uploaded.append(file_name)
        return f"https://example-bucket.oss-example.aliyuncs.com/ims/sys/x/{file_name}"

    def add_row(self, controls):
        self.rows.append(controls)
        return {"code": 200, "data": "row-1", "message": "操作成功"}


def test_push_alert_uses_mcp_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(tmp_path))
    settings = load_settings()
    store = Store(settings.db_path)
    job = Job(
        job_id="job_p",
        run_id="run_p",
        source_type="file",
        media_path="a.jpg",
        captured_at="2026-05-07 17:03:08",
        telemetry=Telemetry(latitude=22.5, longitude=114.1),
    )
    original = tmp_path / "original.jpg"
    detected = tmp_path / "detected.jpg"
    original.write_bytes(b"o")
    detected.write_bytes(b"d")
    writer = _FakeWriter()
    result = _push_alert(
        job=job,
        alert={"alert_type": "fishing", "ims_type": "钓鱼人", "description": "人在水边坐"},
        evidence={"original": str(original), "detected": str(detected)},
        settings=settings,
        store=store,
        writer=writer,
        client=None,
        push_ims=True,
    )
    assert result["status"] == "ok"
    assert result["channel"] == "mcp"
    assert len(writer.uploaded) == 2
    assert len(writer.rows) == 1
    by_id = {row["ctrlId"]: row["value"] for row in writer.rows[0]}
    assert by_id[FIELDS["ai_type"]["cId"]] == "钓鱼人"
    assert by_id[FIELDS["lon"]["cId"]] == "114.1"
    assert by_id[FIELDS["lat"]["cId"]] == "22.5"


def test_ims_retry_does_not_need_models(tmp_path, monkeypatch):
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(tmp_path))
    settings = load_settings()
    store = Store(settings.db_path)
    original = tmp_path / "original.jpg"
    detected = tmp_path / "detected.jpg"
    original.write_bytes(b"o")
    detected.write_bytes(b"d")
    job = Job(
        job_id="job_r",
        run_id="run_r",
        source_type="rtmp",
        media_path="missing.jpg",
        captured_at="2026-09-04T00:00:00Z",
        status="ims_retry",
    )
    store.enqueue(job)
    store.save_result(
        job.job_id,
        job.run_id,
        {
            "confirmed_alerts": [
                {"alert_type": "swimming", "ims_type": "游泳人", "description": "人在水中游泳"}
            ],
            "evidence": {"original": str(original), "detected": str(detected)},
            "ims_push": {"status": "failed"},
        },
    )
    writer = _FakeWriter()
    claimed = store.claim_next()
    out = process_job(
        claimed,
        store=store,
        settings=settings,
        models=None,
        cfg={},
        writer=writer,
        client=None,
        push_ims=True,
        use_vlm=True,
    )
    assert out["ims_push"]["status"] == "ok"
    assert writer.rows
    assert store.get_job(job.job_id).status == "done"
