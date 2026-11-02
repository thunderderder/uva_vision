from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from uva_pra.config import PraConfig, PushConfig
import base64

from uva_pra.feiliu import build_payload, send_live


def test_build_payload_algo_mapping(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"fakejpeg")
    cfg = PraConfig(
        push=PushConfig(
            alert_type_to_algo_id={"游泳人": "11548"},
            feiliu_nest_id="FL-TEST",
        )
    )
    body = build_payload(cfg, {"ims_type": "游泳人"}, str(img))
    assert body["algoId"] == "11548"
    assert body["NestId"] == "FL-TEST"
    raw = img.read_bytes()
    assert body["picData"] == base64.b64encode(raw).decode("ascii")


def test_send_live_retries_once(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        from io import BytesIO

        class R:
            def read(self):
                return b'{"code":200,"message":"ok"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

        return R()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    resp, attempts = send_live("http://example.invalid/x", {"algoId": "1", "NestId": "", "picData": "YQ=="})
    assert resp["code"] == 200
    assert len(attempts) == 2
    assert attempts[0]["status"] == "failed"
    assert attempts[1]["status"] == "ok"
