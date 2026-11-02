from uva.paths import ensure_pipeline_importable

ensure_pipeline_importable()
from modules.vlm_parse import parse_vlm_output


def test_parse_binds_description_to_each_id():
    raw = (
        "ID: 1, Type: person_ok\n"
        "Description: 人在岸边\n"
        "ID: 3, Type: swimming\n"
        "Description: 人在水中，疑似游泳\n"
    )
    parsed = parse_vlm_output(raw)
    by_id = {item["id"]: item for item in parsed["verified_objects"]}
    assert by_id[1]["type"] == "person_ok"
    assert by_id[1]["description"] == "人在岸边"
    assert by_id[3]["type"] == "swimming"
    assert by_id[3]["description"] == "人在水中，疑似游泳"
    assert parsed["description"] == "人在水中，疑似游泳"
    assert parsed["raw_text"] == raw


def test_parse_accepts_bracket_ids_from_full_frame_labels():
    raw = (
        "ID: [1], Type: person_ok\n"
        "Description: 人在岸上内侧\n"
        "ID: [2], Type: false_detect\n"
        "Description: 红框内是枯枝\n"
    )
    parsed = parse_vlm_output(raw)
    by_id = {item["id"]: item for item in parsed["verified_objects"]}
    assert by_id[1]["type"] == "person_ok"
    assert by_id[2]["type"] == "false_detect"
    assert by_id[2]["description"] == "红框内是枯枝"


def test_parse_one_line_id_type_description():
    raw = (
        "ID: [1], Type: fishing, Description: 人在水边蹲着\n"
        "ID: [2], Type: false_detect, Description: 红框是空框\n"
    )
    parsed = parse_vlm_output(raw)
    by_id = {item["id"]: item for item in parsed["verified_objects"]}
    assert by_id[1] == {"id": 1, "type": "fishing", "description": "人在水边蹲着"}
    assert by_id[2] == {"id": 2, "type": "false_detect", "description": "红框是空框"}


def test_parse_keeps_single_block():
    parsed = parse_vlm_output("ID: 2, Type: false_detect\nDescription: 红框是水草")
    assert parsed["verified_objects"] == [
        {"id": 2, "type": "false_detect", "description": "红框是水草"}
    ]
    assert parsed["description"] == "红框是水草"
