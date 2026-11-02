from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from types import SimpleNamespace

from uva_pra.feiliu_logs import collect_feiliu_log_entries, display_document


def test_collect_by_meta_job_id(tmp_path):
    push_dir = tmp_path / "push_records"
    push_dir.mkdir()
    path = push_dir / "feiliu_1.json"
    path.write_text(
        json.dumps(
            {
                "log_version": 1,
                "status": "ok",
                "meta": {"job_id": "job_abc"},
                "request": {"algoId": "11548", "NestId": "", "picData": "YQ=="},
                "attempts": [],
                "response": {"code": 200},
            }
        ),
        encoding="utf-8",
    )
    settings = SimpleNamespace(push_log_dir=push_dir)
    logs = collect_feiliu_log_entries("job_abc", settings=settings, result=None)
    assert len(logs) == 1
    disp = logs[0]["document_display"]
    assert disp["status"] == "ok"
    assert "省略" in disp["request"]["picData"]
    assert "YQ==" not in disp["request"]["picData"]


def test_display_document_omits_picdata():
    doc = {
        "request": {"algoId": "1", "NestId": "", "picData": "A" * 200},
        "response": {"code": 200},
    }
    out = display_document(doc, log_path="/tmp/x.json")
    assert len(out["request"]["picData"]) < 120
    assert "200 字符" in out["request"]["picData"]
