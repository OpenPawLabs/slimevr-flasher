from flasher.builder import BuildArtifacts
from flasher.flash import FlashResult
from flasher.slot import Slot, SlotState
from flasher.verify import Verdict, VerifyResult


def make_artifacts(tmp_path, n_tests=1) -> BuildArtifacts:
    production = tmp_path / "production.bin"
    production.write_bytes(b"")
    tests = []
    for i in range(n_tests):
        bin_path = tmp_path / f"test_{i}.bin"
        bin_path.write_bytes(b"")
        tests.append((f"test/integration/t{i}.cpp", bin_path))
    return BuildArtifacts(production=production, tests=tests, firmware_tag="test-tag")


def passing_flash(port, bin_path, on_progress, on_line):
    on_progress(50)
    on_progress(100)
    return FlashResult(ok=True, returncode=0)


def passing_verify(port, on_line):
    return VerifyResult(Verdict.PASS, [])


def test_happy_path_reaches_pass(tmp_path):
    slot = Slot(
        "COM9",
        make_artifacts(tmp_path),
        flash_fn=passing_flash,
        verify_fn=passing_verify,
    )
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.PASS


def test_test_flash_failure_short_circuits(tmp_path):
    def failing_flash(port, bin_path, on_progress, on_line):
        return FlashResult(ok=False, returncode=1)

    def verify_should_not_run(port, on_line):
        raise AssertionError("verify must not run after a failed test flash")

    slot = Slot(
        "COM9",
        make_artifacts(tmp_path),
        flash_fn=failing_flash,
        verify_fn=verify_should_not_run,
    )
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.FAIL


def test_verify_failure_skips_production(tmp_path):
    artifacts = make_artifacts(tmp_path)
    flashed = []

    def record_flash(port, bin_path, on_progress, on_line):
        flashed.append(bin_path)
        return FlashResult(ok=True, returncode=0)

    def failing_verify(port, on_line):
        return VerifyResult(Verdict.FAIL, [])

    slot = Slot("COM9", artifacts, flash_fn=record_flash, verify_fn=failing_verify)
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.FAIL
    assert artifacts.production not in flashed


def test_all_tests_then_production_in_order(tmp_path):
    artifacts = make_artifacts(tmp_path, n_tests=2)
    flashed = []

    def record_flash(port, bin_path, on_progress, on_line):
        flashed.append(bin_path)
        return FlashResult(ok=True, returncode=0)

    slot = Slot("COM9", artifacts, flash_fn=record_flash, verify_fn=passing_verify)
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.PASS
    assert flashed == [artifacts.tests[0][1], artifacts.tests[1][1], artifacts.production]


def test_production_verify_runs_and_completes(tmp_path):
    artifacts = make_artifacts(tmp_path)
    calls = {"probe": 0, "prod": 0}

    def probe_verify(port, on_line):
        calls["probe"] += 1
        return VerifyResult(Verdict.PASS, [])

    def prod_verify(port, on_line):
        calls["prod"] += 1
        return VerifyResult(Verdict.PASS, [])

    slot = Slot(
        "COM9",
        artifacts,
        flash_fn=passing_flash,
        verify_fn=probe_verify,
        verify_prod_fn=prod_verify,
    )
    slot.set_present(True)
    slot.wait(5)
    snap = slot.snapshot()
    assert snap.state is SlotState.PASS
    assert snap.overall == 100
    assert calls == {"probe": 1, "prod": 1}


def test_production_verify_failure_fails_after_flash(tmp_path):
    artifacts = make_artifacts(tmp_path)
    flashed = []

    def record_flash(port, bin_path, on_progress, on_line):
        flashed.append(bin_path)
        return FlashResult(ok=True, returncode=0)

    def failing_prod_verify(port, on_line):
        return VerifyResult(Verdict.TIMEOUT, [])

    slot = Slot(
        "COM9",
        artifacts,
        flash_fn=record_flash,
        verify_fn=passing_verify,
        verify_prod_fn=failing_prod_verify,
    )
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.FAIL
    # Production firmware was flashed, but its boot verification failed.
    assert artifacts.production in flashed


def test_on_result_fires_once_with_outcome(tmp_path):
    results = []
    slot = Slot(
        "COM9",
        make_artifacts(tmp_path),
        flash_fn=passing_flash,
        verify_fn=passing_verify,
        on_result=results.append,
    )
    slot.set_present(True)
    slot.wait(5)
    assert results == [True]


def test_on_result_reports_failure(tmp_path):
    results = []

    def failing_flash(port, bin_path, on_progress, on_line):
        return FlashResult(ok=False, returncode=1)

    slot = Slot(
        "COM9",
        make_artifacts(tmp_path),
        flash_fn=failing_flash,
        verify_fn=passing_verify,
        on_result=results.append,
    )
    slot.set_present(True)
    slot.wait(5)
    assert results == [False]


def test_rearm_requires_unplug(tmp_path):
    artifacts = make_artifacts(tmp_path)
    calls = {"n": 0}

    def counting_flash(port, bin_path, on_progress, on_line):
        calls["n"] += 1
        return FlashResult(ok=True, returncode=0)

    slot = Slot("COM9", artifacts, flash_fn=counting_flash, verify_fn=passing_verify)

    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.PASS
    after_first = calls["n"]  # 1 test + 1 production

    # Board still present: re-asserting presence must not re-flash.
    slot.set_present(True)
    slot.wait(1)
    assert calls["n"] == after_first

    # Unplug re-arms the slot.
    slot.set_present(False)
    assert slot.snapshot().state is SlotState.ARMED

    # Next board runs the pipeline again.
    slot.set_present(True)
    slot.wait(5)
    assert slot.snapshot().state is SlotState.PASS
    assert calls["n"] == after_first * 2
