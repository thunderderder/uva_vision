from uva.contract import Job, Telemetry
from uva.ims_push import FIELDS, build_field_query_list, source_code
from uva.p1 import SOURCE_RTMP, VERIFY_PENDING


def test_source_code():
    assert source_code("rtmp") == SOURCE_RTMP
    assert source_code("file") == 2


def test_payload_keys_are_cids_not_vmodels():
    job = Job(
        job_id="job_1",
        run_id="run_9",
        source_type="rtmp",
        media_path="a.jpg",
        captured_at="2026-09-03T07:00:00Z",
        telemetry=Telemetry(latitude=22.5, longitude=114.1, water_name="Example Reservoir"),
    )
    alert = {
        "alert_type": "fishing",
        "ims_type": "钓鱼人",
        "description": "岸边有人持竿钓鱼",
        "global_bbox": [10, 20, 40, 80],
    }
    items = build_field_query_list(
        job=job,
        alert=alert,
        idempotency_key="run_9:fishing:0:0",
        detected_url="https://example-bucket.oss-example.aliyuncs.com/a.jpg?x=1",
        original_url="https://example-bucket.oss-example.aliyuncs.com/b.jpg",
        water_name="Example Reservoir",
    )
    by_key = {row["key"]: row for row in items}
    assert FIELDS["source"]["cId"] in by_key
    assert FIELDS["ai_type"]["cId"] in by_key
    assert by_key[FIELDS["ai_type"]["cId"]]["value"] == "钓鱼人"
    assert by_key[FIELDS["verify"]["cId"]]["value"] == VERIFY_PENDING
    assert by_key[FIELDS["issue"]["cId"]]["value"] == "2"
    assert by_key[FIELDS["idem"]["cId"]]["value"] == "run_9:fishing:0:0"
    assert by_key[FIELDS["run_id"]["cId"]]["value"] == "run_9"
    assert "?" not in by_key[FIELDS["det_img"]["cId"]]["value"]
    assert by_key[FIELDS["det_img"]["cType"]] if False else by_key[FIELDS["det_img"]["cId"]]["type"] == 10
    assert "zj_resultImg" not in str(items)
    assert "field361" not in {row["key"] for row in items}
    assert by_key[FIELDS["lon"]["cId"]]["value"] == "114.1"
    assert by_key[FIELDS["lat"]["cId"]]["value"] == "22.5"
