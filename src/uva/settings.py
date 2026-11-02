"""产品壳运行时配置，密钥只从环境变量读。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from uva.paths import ENV_PATH, PROJECT_ROOT, RUNTIME_DIR, load_dotenv


def _mcp_secret() -> str:
    for name in ("IMS_MCP_SECRET", "MCP_SECRET"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


@dataclass
class Settings:
    project_root: Path
    runtime_dir: Path
    db_path: Path
    frames_dir: Path
    evidence_dir: Path
    push_log_dir: Path
    eval_dir: Path
    test_video_dir: Path
    rtmp_url: str
    rtmp_stream: str
    rtmp_pull_url: str
    rtmp_publish_url: str
    rtmp_user: str
    rtmp_password: str
    rtmp_scale_width: int
    frame_interval_s: float
    cooldown_s: float
    dedup_grid: int
    audit_host: str
    audit_port: int
    data_api_auth_url: str
    data_api_username: str
    data_api_password: str
    data_api_aes_key: str
    oss_ak: str
    oss_sk: str
    oss_endpoint: str
    oss_bucket: str
    ims_sys_id: str
    ims_form_id: str
    ims_add_path: str
    ims_mcp_url: str
    ims_mcp_secret: str
    water_name: str
    env_path: Path


def load_settings() -> Settings:
    load_dotenv()
    runtime = Path(os.environ.get("UVA_RUNTIME_DIR", str(RUNTIME_DIR)))
    runtime.mkdir(parents=True, exist_ok=True)
    auth_url = os.environ.get("DATA_API_AUTH_URL", "https://api.example.com").rstrip("/")
    form_id = os.environ.get("UVA_IMS_FORM_ID", "0000000000000000000")
    return Settings(
        project_root=PROJECT_ROOT,
        runtime_dir=runtime,
        db_path=runtime / "uva.sqlite3",
        frames_dir=runtime / "frames",
        evidence_dir=runtime / "evidence",
        push_log_dir=runtime / "push_records",
        eval_dir=PROJECT_ROOT / "data" / "eval_p1",
        test_video_dir=PROJECT_ROOT / "data" / "test_video",
        rtmp_url=os.environ.get("UVA_RTMP_URL", "rtmp://127.0.0.1:1935/live/uva"),
        rtmp_stream=os.environ.get("UVA_RTMP_STREAM", "live/uva"),
        rtmp_pull_url=os.environ.get("UVA_RTMP_PULL_URL", "").strip(),
        rtmp_publish_url=os.environ.get("UVA_RTMP_PUBLISH_URL", "").strip(),
        rtmp_user=os.environ.get("UVA_RTMP_USER", "").strip(),
        rtmp_password=os.environ.get("UVA_RTMP_PASSWORD", "").strip(),
        rtmp_scale_width=int(os.environ.get("UVA_RTMP_SCALE_WIDTH", "1920")),
        frame_interval_s=float(os.environ.get("UVA_FRAME_INTERVAL_S", "2")),
        cooldown_s=float(os.environ.get("UVA_COOLDOWN_S", "2")),
        dedup_grid=int(os.environ.get("UVA_DEDUP_GRID", "160")),
        audit_host=os.environ.get("UVA_AUDIT_HOST", "127.0.0.1"),
        audit_port=int(os.environ.get("UVA_AUDIT_PORT", "8020")),
        data_api_auth_url=auth_url,
        data_api_username=os.environ.get("DATA_API_USERNAME", ""),
        data_api_password=os.environ.get("DATA_API_PASSWORD", ""),
        data_api_aes_key=os.environ.get("DATA_API_AES_KEY", ""),
        oss_ak=os.environ.get("imsOSS_ACCESS_KEY_ID") or os.environ.get("OSS_ACCESS_KEY_ID", ""),
        oss_sk=os.environ.get("imsOSS_ACCESS_KEY_SECRET") or os.environ.get("OSS_ACCESS_KEY_SECRET", ""),
        oss_endpoint=os.environ.get("imsOSS_ENDPOINT", "https://oss-example.aliyuncs.com"),
        oss_bucket=os.environ.get("imsOSS_BUCKET", "example-bucket"),
        ims_sys_id=os.environ.get("UVA_IMS_SYS_ID", "0000000000000000000"),
        ims_form_id=form_id,
        ims_add_path=f"/form/result/add/{form_id}",
        ims_mcp_url=os.environ.get("IMS_MCP_URL") or os.environ.get("MCP_URL") or "https://api.example.com/ims/mcp/",
        ims_mcp_secret=_mcp_secret(),
        water_name=os.environ.get("UVA_WATER_NAME", ""),
        env_path=ENV_PATH,
    )
