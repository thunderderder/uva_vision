"""uva 产品壳命令行。"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from uva.paths import ensure_src_on_path, load_dotenv
from uva.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ensure_src_on_path()
    parser = argparse.ArgumentParser(prog="uva", description="UVA 第一期产品壳")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pipe = sub.add_parser("pipeline", help="单图调试，走 infer_frame")
    p_pipe.add_argument("--image", default=None)

    p_file = sub.add_parser("ingest-file", help="图片或视频入队")
    p_file.add_argument("path")
    p_file.add_argument("--run-id", default=None)

    p_rtmp = sub.add_parser("ingest-rtmp", help="RTMP 抽帧入队（本机模拟或经收流节点）")
    p_rtmp.add_argument("path", nargs="?", default=None, help="可选，等同 --video")
    p_rtmp.add_argument("--video", default=None)
    p_rtmp.add_argument("--duration", type=float, default=20.0)
    p_rtmp.add_argument("--run-id", default=None)
    p_rtmp.add_argument("--edge", action="store_true", help="不启本机 MediaMTX，推/拉 UVA_RTMP_*_URL")
    p_rtmp.add_argument("--pull-url", default=None)
    p_rtmp.add_argument("--publish-url", default=None)
    p_rtmp.add_argument("--no-publish", action="store_true", help="只拉流（无人机已在推）")

    p_pub = sub.add_parser("publish", help="把成片按实时速率推到收流节点")
    p_pub.add_argument("--video", default=None)
    p_pub.add_argument("--url", default=None)
    p_pub.add_argument("--duration", type=float, default=None)

    p_worker = sub.add_parser("worker", help="GPU worker 拉任务")
    p_worker.add_argument("--once", action="store_true")
    p_worker.add_argument("--until-empty", action="store_true")
    p_worker.add_argument("--no-ims", action="store_true")
    p_worker.add_argument("--no-vlm", action="store_true")

    p_audit = sub.add_parser("audit", help="本机技术审计页")
    p_audit.add_argument("--host", default=None)
    p_audit.add_argument("--port", type=int, default=None)

    sub.add_parser("hops", help="逐跳探活：TCP/RTMP 握手 / ECS MediaMTX / 本机队列")

    sub.add_parser("freeze-eval", help="从测试成片冻 P1 抽帧")

    p_qwen = sub.add_parser("download-qwen-vl", help="下载千问 VL（默认 Qwen3-VL-2B-Instruct）到本地 model 目录")
    p_qwen.add_argument(
        "--dir",
        default=None,
        help="目标目录，默认 pipeline config 的 QWEN_DIR_PATH",
    )

    p_pra = sub.add_parser("pra-serve", help="UVA Vision 工作台 Web")
    p_pra.add_argument("--host", default=None)
    p_pra.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "pipeline":
        from uva.kernel import run_still_pipeline

        overrides = {}
        if args.image:
            overrides["TEST_IMAGE_PATH"] = str(Path(args.image).resolve())
        result = run_still_pipeline(overrides or None)
        print(json.dumps({k: v for k, v in result.items() if k != "frame_result"}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "ingest-file":
        from uva.ingest import ingest_path

        run_id, jobs = ingest_path(args.path, run_id=args.run_id)
        gps_n = sum(1 for job in jobs if job.telemetry.latitude is not None and job.telemetry.longitude is not None)
        sample = jobs[0].telemetry.to_dict() if jobs else {}
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "jobs": len(jobs),
                    "gps_frames": gps_n,
                    "sample_telemetry": sample,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "ingest-rtmp":
        from uva.rtmp import default_video, run_simulated_rtmp
        from uva.store import open_store

        settings = load_settings()
        video_arg = args.video or args.path
        if args.edge:
            pull = args.pull_url or settings.rtmp_pull_url
            if not pull:
                raise SystemExit("ingest-rtmp --edge 需要 UVA_RTMP_PULL_URL 或 --pull-url")
            do_publish = not args.no_publish
            video = Path(video_arg) if video_arg else (default_video() if do_publish else None)
            run_id = run_simulated_rtmp(
                video=video,
                run_id=args.run_id,
                duration_s=args.duration,
                settings=settings,
                pull_url=args.pull_url,
                publish_url=args.publish_url,
                start_local_server=False,
                do_publish=do_publish,
            )
        else:
            video = Path(video_arg) if video_arg else default_video()
            run_id = run_simulated_rtmp(
                video=video,
                run_id=args.run_id,
                duration_s=args.duration,
                settings=settings,
            )
        store = open_store(settings)
        cur = store._conn.execute("select payload_json from jobs where run_id = ? order by created_at", (run_id,))
        jobs = [json.loads(row[0]) for row in cur.fetchall()]
        gps_n = sum(1 for job in jobs if (job.get("telemetry") or {}).get("latitude") is not None)
        sample = (jobs[0].get("telemetry") if jobs else {}) or {}
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "jobs": len(jobs),
                    "gps_frames": gps_n,
                    "source_type": "rtmp",
                    "edge": bool(args.edge),
                    "sample_telemetry": sample,
                },
                ensure_ascii=False,
            )
        )
        return 0

    if args.cmd == "publish":
        from uva.rtmp import default_video, run_publish

        video = Path(args.video) if args.video else default_video()
        dest = run_publish(video=video, url=args.url, duration_s=args.duration)
        from uva.rtmp_url import redact_rtmp_url

        print(json.dumps({"published": redact_rtmp_url(dest), "video": str(video)}, ensure_ascii=False))
        return 0

    if args.cmd == "worker":
        from uva.worker import run_worker_loop

        run_worker_loop(
            once=args.once,
            until_empty=args.until_empty,
            push_ims=not args.no_ims,
            use_vlm=not args.no_vlm,
        )
        return 0

    if args.cmd == "audit":
        import uvicorn

        settings = load_settings()
        host = args.host or settings.audit_host
        port = args.port or settings.audit_port
        uvicorn.run("uva.audit_app:app", host=host, port=port, reload=False)
        return 0

    if args.cmd == "hops":
        from uva.hops import collect_hops, format_report

        report = collect_hops()
        print(format_report(report))
        failed = [h for h in report.get("hops") or [] if not h.get("ok")]
        return 1 if failed else 0

    if args.cmd == "freeze-eval":
        from uva.evalset import freeze_eval_set

        manifest = freeze_eval_set()
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "download-qwen-vl":
        from uva.model_assets import ensure_qwen_vl_dir
        from uva.paths import ensure_pipeline_importable

        ensure_pipeline_importable()
        import config

        target = args.dir or config.QWEN_DIR_PATH
        path = ensure_qwen_vl_dir(target, allow_download=True)
        print(json.dumps({"ok": True, "qwen_dir": str(path)}, ensure_ascii=False))
        return 0

    if args.cmd == "pra-serve":
        import uvicorn

        from uva.paths import PROJECT_ROOT

        pra_src = PROJECT_ROOT.parent / "uva_pra" / "src"
        if pra_src.is_dir() and str(pra_src) not in __import__("sys").path:
            __import__("sys").path.insert(0, str(pra_src))
        from uva_pra.bootstrap import ensure_uva_paths
        from uva_pra.config import load_pra_config
        from uva_pra.device import apply_device_policy

        ensure_uva_paths()
        pra = load_pra_config()
        apply_device_policy(pra)
        host = args.host or pra.server.host
        port = args.port or pra.server.port
        uvicorn.run("uva_pra.app:app", host=host, port=port, reload=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
