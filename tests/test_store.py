from pathlib import Path

from uva.contract import Job
from uva.store import Store


def test_enqueue_and_claim(tmp_path: Path):
    store = Store(tmp_path / "uva.sqlite3")
    job = Job(
        job_id="job_1",
        run_id="run_1",
        source_type="file",
        media_path="a.jpg",
        captured_at="2026-09-03T00:00:00Z",
    )
    store.enqueue(job)
    claimed = store.claim_next()
    assert claimed is not None
    assert claimed.job_id == "job_1"
    assert store.claim_next() is None
    store.set_status("job_1", "running")
    assert store.requeue_stuck() == 1
    claimed_again = store.claim_next()
    assert claimed_again is not None
    store.set_status("job_1", "done")
    store.add_event("yolo", run_id="run_1", job_id="job_1", payload={"n": 1})
    runs = store.list_runs()
    assert runs[0]["run_id"] == "run_1"
    events = store.list_events("run_1")
    assert events[0]["kind"] == "yolo"
