from pathlib import Path

from uva.settings import Settings
from uva.store import Store

from uva_pra.test_data_reset import clear_local_test_data


def test_clear_local_test_data(tmp_path: Path):
    runtime = tmp_path / "runtime"
    frames = runtime / "frames"
    evidence = runtime / "evidence"
    push = runtime / "push_records"
    frames.mkdir(parents=True)
    evidence.mkdir(parents=True)
    (frames / "a.jpg").write_bytes(b"x")
    (evidence / "b.jpg").write_bytes(b"y")
    push.mkdir()
    (push / "feiliu_1.json").write_text("{}", encoding="utf-8")

    settings = Settings(
        project_root=tmp_path,
        runtime_dir=runtime,
        db_path=runtime / "uva.sqlite3",
        frames_dir=frames,
        evidence_dir=evidence,
        push_log_dir=push,
        eval_dir=tmp_path / "eval",
        test_video_dir=tmp_path / "video",
        rtmp_url="",
        rtmp_stream="",
        rtmp_pull_url="",
        rtmp_publish_url="",
        rtmp_user="",
        rtmp_password="",
        rtmp_scale_width=1920,
        frame_interval_s=2.0,
        cooldown_s=120.0,
        dedup_grid=160,
        audit_host="127.0.0.1",
        audit_port=8020,
        data_api_auth_url="",
        data_api_username="",
        data_api_password="",
        data_api_aes_key="",
        oss_ak="",
        oss_sk="",
        oss_endpoint="",
        oss_bucket="",
        ims_sys_id="",
        ims_form_id="",
        ims_add_path="",
        ims_mcp_url="",
        ims_mcp_secret="",
        water_name="",
        env_path=tmp_path / ".env",
    )
    store = Store(settings.db_path)
    from uva.contract import Job, new_id

    job = Job(
        job_id=new_id("job_"),
        run_id="run_test",
        source_type="file",
        media_path=str(frames / "a.jpg"),
        captured_at="2020-01-01T00:00:00Z",
    )
    store.enqueue(job)
    store.save_result(job.job_id, job.run_id, {"status": "ok"})

    out = clear_local_test_data(settings, store)
    assert out["ok"]
    assert out["db_deleted"]["jobs"] == 1
    assert not list(frames.iterdir())
    assert store.list_runs() == []
