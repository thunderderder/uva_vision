from fastapi.testclient import TestClient

from uva.audit_app import create_app
from uva.audit_view import (
    _feiliu_label,
    _ims_chip_tone,
    _ims_label,
    beijing_parts,
    build_audit_index,
    build_run_detail,
    project_boxes,
)
from uva.contract import Job
from uva.settings import load_settings
from uva.store import Store


def test_ims_label_dry_run_not_counted_as_pushed():
    label = _ims_label(
        {
            "ims_push": {
                "status": "ok",
                "items": [{"status": "dry_run", "idempotency_key": "run:bucket"}],
            }
        }
    )
    assert label.startswith("未推 IMS")
    assert "已推" not in label

    pushed = _ims_label(
        {
            "ims_push": {
                "status": "ok",
                "items": [{"status": "ok", "channel": "mcp"}],
            }
        }
    )
    assert pushed == "已推 IMS（1）"
    assert _ims_chip_tone({"ims_push": {"status": "ok", "items": [{"status": "dry_run"}]}}) == "muted"
    assert _ims_chip_tone({"ims_push": {"status": "ok", "items": [{"status": "ok"}]}}) == "ok"


def test_feiliu_label_from_result_and_events():
    from uva.audit_view import _feiliu_tooltip

    assert _feiliu_label(None, [], "j1") == "未推"
    assert (
        _feiliu_label(
            {"feiliu_push": {"status": "ok", "items": [{"status": "record_only"}]}},
            [],
            "j1",
        )
        == "演练落盘（1）"
    )
    assert "演练落盘" in _feiliu_tooltip(
        {"feiliu_push": {"status": "ok", "items": [{"status": "record_only"}]}},
        [],
        "j1",
    )
    assert (
        _feiliu_label(
            {
                "feiliu_push": {
                    "status": "ok",
                    "items": [
                        {
                            "status": "ok",
                            "response": {"code": 200, "message": "操作成功", "data": {}},
                        }
                    ],
                }
            },
            [],
            "j1",
        )
        == "200 操作成功"
    )
    assert (
        _feiliu_label(
            None,
            [{"kind": "feiliu_push", "job_id": "j1", "payload": {"status": "ok"}}],
            "j1",
        )
        == "已推"
    )
    assert (
        _feiliu_label(
            {
                "feiliu_push": {
                    "status": "ok",
                    "items": [{"status": "failed", "response": {"code": 401, "message": "无权限"}}],
                }
            },
            [],
            "j1",
        )
        == "401 无权限"
    )


def test_beijing_date_from_utc():
    date, clock = beijing_parts("2026-09-03T08:11:22Z")
    assert date == "2026-09-03"
    assert clock == "16:11"


def test_project_boxes_keeps_yolo_conf_and_qwen_label():
    boxes = project_boxes(
        {
            "detections": [
                {"id": 1, "class_name": "person", "confidence": 0.126, "global_bbox": [10, 20, 30, 40]}
            ],
            "qwen_results": [
                {
                    "detection_id": 1,
                    "verified_objects": [{"id": 1, "type": "normal"}],
                    "description": "岸边站立",
                }
            ],
            "alarms": [{"id": 1, "type": "normal", "status": "false_alarm"}],
        }
    )
    assert boxes[0]["id"] == 1
    assert boxes[0]["yolo_confidence"] == 0.126
    assert boxes[0]["qwen_label"] == "人对了，无危险行为"
    assert boxes[0]["qwen_description"] == "岸边站立"


def test_project_boxes_ignores_string_confidence():
    boxes = project_boxes(
        {
            "detections": [
                {"id": 1, "class_name": "person", "confidence": "high", "global_bbox": [0, 0, 8, 8]}
            ]
        }
    )
    assert boxes[0]["yolo_confidence"] is None


def test_project_boxes_reads_yolo_confidence_field():
    boxes = project_boxes(
        {
            "detections": [
                {
                    "id": 1,
                    "class_name": "person",
                    "confidence": "high",
                    "yolo_confidence": 0.057,
                    "global_bbox": [0, 0, 8, 8],
                }
            ]
        }
    )
    assert boxes[0]["yolo_confidence"] == 0.057


def test_project_boxes_marks_qwen_flip():
    boxes = project_boxes(
        {
            "detections": [{"id": 1, "class_name": "person", "confidence": 0.2, "global_bbox": [0, 0, 8, 8]}],
            "qwen_results": [
                {"detection_id": 1, "verified_objects": [{"id": 1, "type": "normal"}], "description": "岸边"}
            ],
            "alarms": [{"id": 1, "type": "normal", "status": "false_alarm"}],
        },
        qwen_passes=[
            {
                "time": "17:21",
                "boxes": [{"id": 1, "qwen_type": "swimming", "qwen_label": "游泳人", "description": "水中"}],
            },
            {
                "time": "17:24",
                "boxes": [{"id": 1, "qwen_type": "normal", "qwen_label": "人对了，无危险行为", "description": "岸边"}],
            },
        ],
    )
    assert boxes[0]["flipped"] is True
    assert [h["qwen_label"] for h in boxes[0]["history"]] == ["游泳人", "人对了，无危险行为"]


def test_audit_groups_by_date_and_lists_boxes(tmp_path, monkeypatch):
    monkeypatch.setenv("UVA_RUNTIME_DIR", str(tmp_path))
    settings = load_settings()
    store = Store(settings.db_path)
    store.enqueue(
        Job(
            job_id="job_a",
            run_id="run_a",
            source_type="file",
            media_path="x.jpg",
            captured_at="2026-09-03T08:00:00Z",
            created_at="2026-09-03T08:00:00Z",
        )
    )
    store.set_status("job_a", "done")
    store.save_result(
        "job_a",
        "run_a",
        {
            "detections": [
                {"id": 1, "class_name": "person", "confidence": 0.5, "global_bbox": [1, 2, 3, 4]}
            ],
            "qwen_results": [
                {
                    "detection_id": 1,
                    "verified_objects": [{"id": 1, "type": "swimming"}],
                    "description": "水中扑腾",
                }
            ],
            "alarms": [{"id": 1, "type": "swimming", "status": "confirmed_alarm", "ims_type": "游泳人"}],
            "confirmed_alerts": [{"ims_type": "游泳人"}],
            "skipped_reason": None,
            "evidence": {},
        },
    )
    index = build_audit_index(store)
    assert index["dates"][0]["date"] == "2026-09-03"
    assert index["dates"][0]["runs"][0]["source_label"] == "文件"
    detail = build_run_detail(store, "run_a")
    box = detail["jobs"][0]["boxes"][0]
    assert box["qwen_label"] == "游泳人"
    assert box["yolo_confidence"] == 0.5

    app = create_app()
    client = TestClient(app)
    html = client.get("/")
    assert html.status_code == 200
    assert "Qwen 复核" in html.text
    assert "原始 JSON" in html.text
    runs = client.get("/api/runs").json()
    assert runs["dates"][0]["runs"][0]["run_id"] == "run_a"
    payload = client.get("/api/runs/run_a").json()
    assert payload["jobs"][0]["boxes"][0]["id"] == 1
    assert payload["jobs"][0]["boxes"][0]["qwen_label"] == "游泳人"
