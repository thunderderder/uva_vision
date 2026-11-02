from uva.contract import Job, SCHEMA_VERSION, Telemetry
from uva.p1 import classify_vlm_type, sanitize_description


def test_job_roundtrip():
    job = Job.from_dict(
        {
            "job_id": "job_a",
            "run_id": "run_b",
            "source_type": "rtmp",
            "media_path": "x.jpg",
            "captured_at": "2026-09-03T00:00:00Z",
            "telemetry": {"latitude": 22.5, "longitude": 114.1, "water_name": "Example Reservoir"},
        }
    )
    again = Job.from_json(job.dumps())
    assert again.job_id == "job_a"
    assert again.source_type == "rtmp"
    assert again.telemetry.latitude == 22.5
    assert again.schema_version == SCHEMA_VERSION


def test_classify_vlm_type():
    assert classify_vlm_type("fishing") == "fishing"
    assert classify_vlm_type("钓鱼人") == "fishing"
    assert classify_vlm_type("swimming") == "swimming"
    assert classify_vlm_type("normal") is None
    assert classify_vlm_type("person") is None
    assert classify_vlm_type("person_ok") is None
    assert classify_vlm_type("false_detect") is None
    assert classify_vlm_type("误报") is None
    assert classify_vlm_type("fishing/swimming/normal") is None
    assert classify_vlm_type("netting") == "fishing"
    assert classify_vlm_type("打网") == "fishing"
    assert classify_vlm_type("drowning") == "drowning"
    assert classify_vlm_type("溺水人") == "drowning"
    assert classify_vlm_type("no_life_jacket") == "no_life_jacket"
    assert classify_vlm_type("临水未穿救生衣") == "no_life_jacket"


def test_normalize_vlm_verdict():
    from uva.p1 import normalize_vlm_verdict

    assert normalize_vlm_verdict("person_ok") == "person_ok"
    assert normalize_vlm_verdict("false_detect") == "false_detect"
    assert normalize_vlm_verdict("误报") == "false_detect"
    assert normalize_vlm_verdict("人对了但没有危险行为") == "person_ok"


def test_sanitize_forbids_empty_anomaly_phrase():
    text = sanitize_description("未发现异常", "fishing")
    assert "未发现异常" not in text
    assert "钓鱼" in text
