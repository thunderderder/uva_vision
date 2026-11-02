from __future__ import annotations

import sys
from pathlib import Path

PRA_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PRA_SRC) not in sys.path:
    sys.path.insert(0, str(PRA_SRC))

from uva_pra.config import PraConfig, DeviceConfig, InferenceConfig, _from_mapping


def test_effective_use_vlm_requires_gpu():
    cfg = PraConfig(
        device=DeviceConfig(gpu_enabled=False),
        inference=InferenceConfig(vlm_enabled=True, yolo_enabled=True),
    )
    assert cfg.effective_use_vlm() is False

    cfg.device.gpu_enabled = True
    assert cfg.effective_use_vlm() is True

    cfg.inference.vlm_enabled = False
    assert cfg.effective_use_vlm() is False


def test_from_mapping_roundtrip_keys():
    data = {
        "device": {"gpu_enabled": True},
        "inference": {"vlm_enabled": False, "yolo_enabled": True},
        "runtime": {"YOLO_CONF_THRESHOLD": 0.3},
    }
    cfg = _from_mapping(data)
    assert cfg.runtime["YOLO_CONF_THRESHOLD"] == 0.3
    assert cfg.device.gpu_enabled is True
