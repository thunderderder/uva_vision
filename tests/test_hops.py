from uva.hops import summarize_conns, summarize_path


def test_summarize_path_ready():
    payload = {
        "items": [
            {
                "name": "live/uva",
                "ready": True,
                "tracks": ["H264"],
                "bytesReceived": 12000,
                "readers": [{"id": "1"}],
            }
        ]
    }
    info = summarize_path(payload, "live/uva")
    assert info["ready"] is True
    assert info["readers"] == 1
    assert info["bytesReceived"] == 12000


def test_summarize_path_missing():
    info = summarize_path({"items": []}, "live/uva")
    assert info["found"] is False
    assert info["ready"] is False


def test_summarize_conns_publish_and_read():
    payload = {
        "items": [
            {
                "path": "live/uva",
                "state": "publish",
                "remoteAddr": "1.1.1.1:9",
                "bytesReceived": 100,
            },
            {
                "path": "live/uva",
                "state": "read",
                "remoteAddr": "2.2.2.2:8",
                "bytesSent": 80,
            },
            {"path": "live/other", "state": "publish", "remoteAddr": "9.9.9.9:1"},
        ]
    }
    info = summarize_conns(payload, "live/uva")
    assert len(info["publishers"]) == 1
    assert info["publishers"][0]["addr"] == "1.1.1.1:9"
    assert len(info["readers"]) == 1


def test_summarize_path_ready():
    payload = {
        "items": [
            {
                "name": "live/uva",
                "ready": True,
                "tracks": ["H264"],
                "bytesReceived": 12000,
                "readers": [{"id": "1"}],
            }
        ]
    }
    info = summarize_path(payload, "live/uva")
    assert info["ready"] is True
    assert info["readers"] == 1
    assert info["bytesReceived"] == 12000


def test_summarize_path_missing():
    info = summarize_path({"items": []}, "live/uva")
    assert info["found"] is False
    assert info["ready"] is False
