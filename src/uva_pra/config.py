from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from uva_pra.bootstrap import PRA_ROOT

DEFAULTS_PATH = PRA_ROOT / "config" / "pra_defaults.yaml"
RUNTIME_PATH = PRA_ROOT / "config" / "pra_runtime.yaml"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8030


@dataclass
class DeviceConfig:
    gpu_enabled: bool = False


@dataclass
class InferenceConfig:
    vlm_enabled: bool = False
    yolo_enabled: bool = True


@dataclass
class IngestConfig:
    rtmp_frame_interval_sec: float = 2.0
    # direct_local：本机 MediaMTX，外部直推（常驻服务器推荐，不经 ECS）
    # edge_relay：从 UVA_RTMP_PULL_URL 拉流（司空→ECS 旧路径）
    # remote_pull：从 rtmp_custom_pull_url 拉流（萤石 openlive 等，不启本机 MTX）
    # simulate：本机用 mp4 模拟推流
    rtmp_mode: str = "direct_local"
    rtmp_custom_pull_url: str = ""
    image_folder_path: str = ""
    # 同一画面格内多久内不重复跑千问（秒）；无人机 RTMP 建议与抽帧间隔接近（约 2）
    vlm_person_cooldown_sec: float = 2.0


@dataclass
class PushConfig:
    ims_enabled: bool = False
    feiliu_enabled: bool = False
    feiliu_mode: str = "record_only"
    feiliu_url: str = ""
    feiliu_nest_id: str = ""
    alert_type_to_algo_id: dict[str, str] = field(default_factory=dict)


@dataclass
class PraConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    inference: InferenceConfig = field(default_factory=InferenceConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    runtime: dict[str, Any] = field(default_factory=dict)
    push: PushConfig = field(default_factory=PushConfig)

    def effective_use_vlm(self) -> bool:
        if not self.device.gpu_enabled:
            return False
        if not self.inference.vlm_enabled:
            return False
        return True

    def effective_yolo(self) -> bool:
        return bool(self.inference.yolo_enabled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": {"host": self.server.host, "port": self.server.port},
            "device": {
                "gpu_enabled": self.device.gpu_enabled,
            },
            "inference": {
                "vlm_enabled": self.inference.vlm_enabled,
                "yolo_enabled": self.inference.yolo_enabled,
                "effective_use_vlm": self.effective_use_vlm(),
            },
            "ingest": {
                "rtmp_frame_interval_sec": self.ingest.rtmp_frame_interval_sec,
                "rtmp_mode": self.ingest.rtmp_mode,
                "rtmp_custom_pull_url": self.ingest.rtmp_custom_pull_url,
                "image_folder_path": self.ingest.image_folder_path,
                "vlm_person_cooldown_sec": self.ingest.vlm_person_cooldown_sec,
            },
            "runtime": dict(self.runtime),
            "push": {
                "ims_enabled": self.push.ims_enabled,
                "feiliu_enabled": self.push.feiliu_enabled,
                "feiliu_mode": self.push.feiliu_mode,
                "feiliu_url": self.push.feiliu_url,
                "feiliu_nest_id": self.push.feiliu_nest_id,
                "alert_type_to_algo_id": dict(self.push.alert_type_to_algo_id),
            },
        }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _from_mapping(data: dict[str, Any]) -> PraConfig:
    server = data.get("server") or {}
    device = data.get("device") or {}
    inference = data.get("inference") or {}
    ingest = data.get("ingest") or {}
    push = data.get("push") or {}
    return PraConfig(
        server=ServerConfig(
            host=str(server.get("host", "127.0.0.1")),
            port=int(server.get("port", 8030)),
        ),
        device=DeviceConfig(
            gpu_enabled=bool(device.get("gpu_enabled", False)),
        ),
        inference=InferenceConfig(
            vlm_enabled=bool(inference.get("vlm_enabled", False)),
            yolo_enabled=bool(inference.get("yolo_enabled", True)),
        ),
        ingest=IngestConfig(
            rtmp_frame_interval_sec=float(ingest.get("rtmp_frame_interval_sec", 2.0)),
            rtmp_mode=str(ingest.get("rtmp_mode", "direct_local")),
            rtmp_custom_pull_url=str(ingest.get("rtmp_custom_pull_url", "") or "").strip(),
            image_folder_path=str(ingest.get("image_folder_path", "") or "").strip(),
            vlm_person_cooldown_sec=float(ingest.get("vlm_person_cooldown_sec", 2.0)),
        ),
        runtime=dict(data.get("runtime") or {}),
        push=PushConfig(
            ims_enabled=bool(push.get("ims_enabled", False)),
            feiliu_enabled=bool(push.get("feiliu_enabled", False)),
            feiliu_mode=str(push.get("feiliu_mode", "record_only")),
            feiliu_url=str(push.get("feiliu_url", "")),
            feiliu_nest_id=str(push.get("feiliu_nest_id", "")),
            alert_type_to_algo_id=dict(push.get("alert_type_to_algo_id") or {}),
        ),
    )


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return data if isinstance(data, dict) else {}


def load_pra_config() -> PraConfig:
    merged = _deep_merge(load_yaml(DEFAULTS_PATH), load_yaml(RUNTIME_PATH))
    return _from_mapping(merged)


def save_pra_runtime(patch: dict[str, Any]) -> PraConfig:
    """合并写入 pra_runtime.yaml（不修改 defaults）。"""
    current = _deep_merge(load_yaml(DEFAULTS_PATH), load_yaml(RUNTIME_PATH))
    merged = _deep_merge(current, patch)
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_PATH.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return _from_mapping(merged)


def runtime_overrides_for_uva(cfg: PraConfig) -> dict[str, Any]:
    """传给 uva.kernel.runtime_config 的 overrides。"""
    return dict(cfg.runtime)
