"""uva_pra 命令行：serve / worker（读 pra 配置，含 GPU / 千问开关）。"""

from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    from uva_pra.bootstrap import ensure_uva_paths

    ensure_uva_paths()

    parser = argparse.ArgumentParser(prog="uva_pra", description="UVA Vision workbench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="启动 Web 工作台")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)

    p_worker = sub.add_parser("worker", help="GPU/CPU worker（读 pra 配置）")
    p_worker.add_argument("--once", action="store_true")
    p_worker.add_argument("--until-empty", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from uva_pra.config import load_pra_config, runtime_overrides_for_uva
    from uva_pra.device import apply_device_policy

    pra = load_pra_config()
    apply_device_policy(pra)

    if args.cmd == "serve":
        import uvicorn

        host = args.host or pra.server.host
        port = args.port or pra.server.port
        uvicorn.run("uva_pra.app:app", host=host, port=port, reload=False)
        return 0

    if args.cmd == "worker":
        import os

        from uva.worker import run_worker_loop

        os.environ["UVA_FRAME_INTERVAL_S"] = str(pra.ingest.rtmp_frame_interval_sec)
        os.environ["UVA_COOLDOWN_S"] = str(pra.ingest.vlm_person_cooldown_sec)
        use_vlm = pra.effective_use_vlm()
        if pra.inference.vlm_enabled and not pra.device.gpu_enabled:
            logging.warning("vlm_enabled=true 但 gpu_enabled=false，已跳过千问加载")
        if not pra.effective_yolo():
            raise SystemExit("inference.yolo_enabled=false，worker 无意义")

        run_worker_loop(
            once=args.once,
            until_empty=args.until_empty,
            push_ims=pra.push.ims_enabled,
            use_vlm=use_vlm,
            runtime_overrides=runtime_overrides_for_uva(pra),
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
