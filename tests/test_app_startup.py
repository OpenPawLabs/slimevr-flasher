"""Headless TUI smoke tests via Textual's run_test().

These guard against regressions in app startup and the arm -> slot wiring,
including accidental shadowing of Textual App internals (e.g. `_ready`) and the
two-panel control/status layout. Skipped automatically if textual is not
installed.
"""

import asyncio
import threading
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import RichLog  # noqa: E402

from flasher import app as appmod  # noqa: E402
from flasher import builder, flash, ports, verify  # noqa: E402
from flasher.config import load_board_config  # noqa: E402
from flasher.flash import FlashResult  # noqa: E402
from flasher.slot import SlotState  # noqa: E402
from flasher.verify import Verdict, VerifyResult  # noqa: E402
from flasher.widgets import SlotCard  # noqa: E402


def _stub_build(tests):
    return lambda cfg, on_line=None, **kwargs: builder.BuildArtifacts(
        production=Path("prod.bin"), tests=tests, firmware_tag="test-tag"
    )


def _pass_flash(port, bin_path, on_progress=None, on_line=None):
    if on_progress:
        on_progress(100)
    return FlashResult(ok=True, returncode=0)


def _pass_verify(port, on_line=None):
    return VerifyResult(Verdict.PASS, [])


def _pass_prod_verify(port, on_line=None):
    from flasher.verify import ProductionVerifyResult, StepResult, Verdict

    return ProductionVerifyResult(
        verdict=Verdict.PASS,
        mac_address="F0:24:F9:D2:8C:74",
        firmware_commit="c12c475",
        boot_check=StepResult.PASS,
        get_info=StepResult.PASS,
        wifi_scan=StepResult.PASS,
        factory_reset=StepResult.PASS,
    )


async def _wait(pilot, predicate, tries=80):
    for _ in range(tries):
        await pilot.pause(0.05)
        if predicate():
            return True
    return False


def test_app_reaches_ready(monkeypatch):
    monkeypatch.setattr(builder, "build_all", _stub_build([]))
    monkeypatch.setattr(ports, "list_serial_ports", lambda: set())
    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(pilot, lambda: app._build_ready)
        assert app._build_ready

    asyncio.run(go())


def test_log_widget_is_richlog(monkeypatch):
    monkeypatch.setattr(builder, "build_all", _stub_build([]))
    monkeypatch.setattr(ports, "list_serial_ports", lambda: set())
    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(pilot, lambda: app._build_ready)
            log = app.query_one("#log", RichLog)
            assert log.auto_scroll is True

    asyncio.run(go())


def test_app_arms_port_and_ships(monkeypatch):
    monkeypatch.setattr(
        builder, "build_all", _stub_build([("test/integration/x.cpp", Path("t.bin"))])
    )
    monkeypatch.setattr(ports, "list_serial_ports", lambda: {"COM_TEST"})
    monkeypatch.setattr(flash, "flash", _pass_flash)
    monkeypatch.setattr(verify, "monitor", _pass_verify)
    monkeypatch.setattr(verify, "monitor_production_suite", lambda port, cfg, on_line=None: _pass_prod_verify(port, on_line))

    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(
                pilot, lambda: app._build_ready and "COM_TEST" in app._candidate_ports
            )
            app.action_arm_all()
            await _wait(
                pilot,
                lambda: "COM_TEST" in app.slots
                and app.slots["COM_TEST"].snapshot().state in (SlotState.PASS, SlotState.FAIL),
            )
        snap = app.slots["COM_TEST"].snapshot()
        assert snap.state is SlotState.PASS
        assert snap.overall == 100
        # Session statistics tallied the completed run.
        assert (app._n_total, app._n_pass, app._n_fail) == (1, 1, 0)

    asyncio.run(go())


def test_passed_card_has_pass_class(monkeypatch):
    monkeypatch.setattr(
        builder, "build_all", _stub_build([("test/integration/x.cpp", Path("t.bin"))])
    )
    monkeypatch.setattr(ports, "list_serial_ports", lambda: {"COM_TEST"})
    monkeypatch.setattr(flash, "flash", _pass_flash)
    monkeypatch.setattr(verify, "monitor", _pass_verify)
    monkeypatch.setattr(verify, "monitor_production_suite", lambda port, cfg, on_line=None: _pass_prod_verify(port, on_line))

    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(pilot, lambda: app._build_ready and bool(app._candidate_ports))
            app.action_arm_all()
            await _wait(
                pilot,
                lambda: "COM_TEST" in app._cards
                and app._cards["COM_TEST"].has_class("-pass"),
            )
            card = app.query_one(SlotCard)
            assert card.has_class("-pass")

    asyncio.run(go())


def test_toggle_arms_then_disarms(monkeypatch):
    monkeypatch.setattr(
        builder, "build_all", _stub_build([("test/integration/x.cpp", Path("t.bin"))])
    )
    monkeypatch.setattr(ports, "list_serial_ports", lambda: {"COM_TEST"})
    monkeypatch.setattr(flash, "flash", _pass_flash)
    monkeypatch.setattr(verify, "monitor", _pass_verify)
    monkeypatch.setattr(verify, "monitor_production_suite", lambda port, cfg, on_line=None: _pass_prod_verify(port, on_line))

    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(pilot, lambda: app._build_ready and "COM_TEST" in app._candidate_ports)
            app._arm("COM_TEST")
            assert "COM_TEST" in app.slots
            # Let it finish (terminal state) so disarm is permitted.
            await _wait(
                pilot,
                lambda: app.slots["COM_TEST"].snapshot().state in (SlotState.PASS, SlotState.FAIL),
            )
            app._disarm("COM_TEST")
            assert "COM_TEST" not in app.slots

    asyncio.run(go())


def test_disarm_blocked_while_flashing(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def gated_flash(port, bin_path, on_progress=None, on_line=None):
        started.set()
        release.wait(2.0)
        if on_progress:
            on_progress(100)
        return FlashResult(ok=True, returncode=0)

    monkeypatch.setattr(
        builder, "build_all", _stub_build([("test/integration/x.cpp", Path("t.bin"))])
    )
    monkeypatch.setattr(ports, "list_serial_ports", lambda: {"COM_TEST"})
    monkeypatch.setattr(flash, "flash", gated_flash)
    monkeypatch.setattr(verify, "monitor", _pass_verify)
    monkeypatch.setattr(verify, "monitor_production_suite", lambda port, cfg, on_line=None: _pass_prod_verify(port, on_line))

    app = appmod.FlasherApp(load_board_config())

    async def go():
        async with app.run_test() as pilot:
            await _wait(pilot, lambda: app._build_ready and "COM_TEST" in app._candidate_ports)
            app.action_arm_all()
            await _wait(pilot, started.is_set)
            app._disarm("COM_TEST")  # should be a no-op mid-flash
            assert "COM_TEST" in app.slots
            release.set()
            await _wait(
                pilot,
                lambda: app.slots["COM_TEST"].snapshot().state in (SlotState.PASS, SlotState.FAIL),
            )
        assert app.slots["COM_TEST"].snapshot().state is SlotState.PASS

    asyncio.run(go())
