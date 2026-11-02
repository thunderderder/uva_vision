from uva.rtmp import run_simulated_rtmp
from uva.settings import load_settings


def test_edge_does_not_start_local_mtx(tmp_path, monkeypatch):
    started = {"mtx": 0}

    def boom():
        started["mtx"] += 1
        raise AssertionError("edge 不应启动本机 MediaMTX")

    monkeypatch.setattr("uva.rtmp.start_mediamtx", boom)

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr("uva.rtmp._wait_for_rtmp_grabber", lambda *a, **k: FakeProc())
    monkeypatch.setattr("uva.rtmp.watch_jpegs", lambda *a, **k: 1)
    settings = load_settings()
    settings.runtime_dir = tmp_path
    settings.frames_dir = tmp_path / "frames"
    settings.db_path = tmp_path / "t.sqlite3"
    run_id = run_simulated_rtmp(
        video=None,
        duration_s=1,
        settings=settings,
        start_local_server=False,
        do_publish=False,
        pull_url="rtmp://example.invalid:1935/live/uva",
        run_id="run_edge_test",
    )
    assert run_id == "run_edge_test"
    assert started["mtx"] == 0
