import hashlib
import json

from uva.paths import EVAL_DIR, ensure_pipeline_importable


def test_frozen_p1_v1_matches_live_config():
    ensure_pipeline_importable()
    import config

    frozen = json.loads((EVAL_DIR / "frozen" / "p1_v1_20260904.json").read_text(encoding="utf-8"))
    prompt = (EVAL_DIR / "frozen" / frozen["prompt_file"]).read_text(encoding="utf-8")
    digest = hashlib.sha256(config.VLM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
    assert config.FROZEN_PROMPT_ID == frozen["id"]
    assert config.VLM_PROMPT_TEMPLATE == prompt
    assert digest == frozen["prompt_sha256"]
    assert config.VLM_LAYOUT_BY_SOURCE == frozen["layout"]
    assert config.VLM_ALERT_GUIDE == frozen["vlm_alert_guide"]
    gold = json.loads((EVAL_DIR / "gold_30m_human.json").read_text(encoding="utf-8"))
    assert gold["frozen_as"] == frozen["id"]
