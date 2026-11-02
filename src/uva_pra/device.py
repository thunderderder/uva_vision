from __future__ import annotations

import os

from uva_pra.config import PraConfig


def apply_device_policy(cfg: PraConfig) -> None:
    """在 import torch / load_models 之前调用。"""
    if cfg.device.gpu_enabled:
        os.environ.pop("UVA_FORCE_CPU", None)
        # 不主动改 CUDA_VISIBLE_DEVICES，交给服务器上的默认 GPU
        return
    os.environ["UVA_FORCE_CPU"] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
