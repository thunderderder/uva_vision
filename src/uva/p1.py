"""P1 类别、Qwen 判定映射、IMS 业务取值。"""

from __future__ import annotations

YOLO_CLASSES = ["person"]
VLM_TARGET_TYPES = ["fishing", "swimming", "drowning", "no_life_jacket"]

IMS_TYPE = {
    "fishing": "钓鱼人",
    "swimming": "游泳人",
    "drowning": "溺水人",
    "no_life_jacket": "临水未穿救生衣",
}

VLM_VERDICT_LABEL = {
    **IMS_TYPE,
    "person_ok": "人对了，无危险行为",
    "false_detect": "误报",
}

# 检测问题 field111：钓鱼→2，游泳→5；溺水/临水未穿救生衣待 IMS 侧确认后补码
ISSUE_CODE = {
    "fishing": "2",
    "swimming": "5",
    "drowning": "",
    "no_life_jacket": "",
}

SOURCE_FILE = 2  # AI媒体文件识别
SOURCE_RTMP = 3  # AI直播抽帧识别
VERIFY_PENDING = 1
DISPATCH_NO = 2

FORBIDDEN_RESULT_PHRASE = "未发现异常"

PERSON_CLASS_NAMES = {"person", "human", "people", "man", "woman"}


def normalize_vlm_verdict(raw: str | None) -> str | None:
    """收成 fishing / swimming / person_ok / false_detect。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if "/" in text or "或" in text:
        return None
    compact = text.lower().replace("-", "_").replace(" ", "")
    aliases = {
        "fishing": "fishing",
        "swimming": "swimming",
        "drowning": "drowning",
        "nolifejacket": "no_life_jacket",
        "no_life_jacket": "no_life_jacket",
        "shore_no_life_jacket": "no_life_jacket",
        "person_ok": "person_ok",
        "personok": "person_ok",
        "safe": "person_ok",
        "normal": "person_ok",
        "false_detect": "false_detect",
        "falsedetect": "false_detect",
        "false_positive": "false_detect",
        "falsepositive": "false_detect",
        "misdetect": "false_detect",
        "unknown": None,
    }
    if compact in aliases:
        return aliases[compact]
    if "误报" in text or "不是人" in text or "假目标" in text:
        return "false_detect"
    if "没有危险" in text or "无危险" in text or "人对了" in text or "非预警" in text:
        return "person_ok"
    if "drown" in compact or "溺水" in text or "没入" in text:
        return "drowning"
    if "swim" in compact or "游泳" in text:
        return "swimming"
    if "lifejacket" in compact or "救生衣" in text or "浮具" in text and "未穿" in text:
        return "no_life_jacket"
    if "fish" in compact or "钓" in text or "netting" in compact or "打网" in text or "撒网" in text:
        return "fishing"
    if compact in {"net", "nets"}:
        return "fishing"
    return None


def classify_vlm_type(raw: str | None) -> str | None:
    """预警类型 fishing / swimming；人对了、误报、其它一律非预警。"""
    verdict = normalize_vlm_verdict(raw)
    if verdict in VLM_TARGET_TYPES:
        return verdict
    return None


def sanitize_description(text: str | None, alert_type: str | None) -> str:
    desc = (text or "").strip()
    if FORBIDDEN_RESULT_PHRASE in desc:
        desc = desc.replace(FORBIDDEN_RESULT_PHRASE, "").strip(" ，,。;；")
    if not desc and alert_type:
        desc = f"疑似{IMS_TYPE[alert_type]}"
    if not desc:
        desc = "疑似违规亲水行为"
    if FORBIDDEN_RESULT_PHRASE in desc:
        desc = f"疑似{IMS_TYPE.get(alert_type or '', '违规亲水行为')}"
    return desc[:80]


def is_person_class(name: str | None) -> bool:
    return str(name or "").strip().lower() in PERSON_CLASS_NAMES
