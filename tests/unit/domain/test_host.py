from locks_lab.domain.host import HostLoad


def test_a_load_above_half_a_task_per_cpu_is_a_loaded_machine():
    assert HostLoad(40.0, 12).loaded
    assert not HostLoad(3.0, 12).loaded
    assert not HostLoad(6.0, 12).loaded


def test_the_note_names_the_load_and_says_what_to_do_when_it_is_high():
    loaded = HostLoad(39.5, 12).note()
    assert "loaded machine (load average 39.5 on 12 CPUs)" in loaded
    assert "rerun `make run`" in loaded
    assert HostLoad(2.0, 12).note() == "Measured at load average 2.0 on 12 CPUs."
