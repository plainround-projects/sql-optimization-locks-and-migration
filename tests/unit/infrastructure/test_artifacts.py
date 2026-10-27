from locks_lab.infrastructure.artifacts import FileArtifactStore


def test_a_plan_is_written_as_name_dot_txt(tmp_path):
    store = FileArtifactStore(tmp_path / "out")
    store.save_plan("f1_stale_statistics", ["Seq Scan on events", "Execution Time: 1.0 ms"])
    assert (tmp_path / "out" / "f1_stale_statistics.txt").read_text() == "Seq Scan on events\nExecution Time: 1.0 ms\n"


def test_a_text_capture_keeps_its_own_name(tmp_path):
    FileArtifactStore(tmp_path).save_text("lock_queue.txt", "queue\n")
    assert (tmp_path / "lock_queue.txt").read_text() == "queue\n"


def test_the_report_is_written_as_results_md(tmp_path):
    FileArtifactStore(tmp_path).save_report("# Results\n")
    assert (tmp_path / "results.md").read_text() == "# Results\n"
