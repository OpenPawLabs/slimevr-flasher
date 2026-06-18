"""Pure-function tests for the TUI presentation helpers (no running app)."""

from flasher.slot import SlotState, SlotView
from flasher.widgets import port_row_label, state_class, state_label


def _view(state: SlotState, *, present: bool = True) -> SlotView:
    return SlotView(
        port="COM3",
        state=state,
        progress=0,
        overall=0,
        message="",
        current_test=None,
        present=present,
    )


def test_state_label_covers_every_state():
    assert state_label(SlotState.ARMED) == "WAITING"
    assert state_label(SlotState.FLASHING_TEST) == "FLASH TEST"
    assert state_label(SlotState.VERIFYING) == "VERIFYING"
    assert state_label(SlotState.FLASHING_PROD) == "FLASH PROD"
    assert state_label(SlotState.VERIFYING_PROD) == "VERIFY PROD"
    assert state_label(SlotState.PASS) == "PASS"
    assert state_label(SlotState.FAIL) == "FAIL"


def test_state_class_buckets():
    assert state_class(SlotState.ARMED) == "-idle"
    assert state_class(SlotState.FLASHING_TEST) == "-active"
    assert state_class(SlotState.VERIFYING) == "-active"
    assert state_class(SlotState.FLASHING_PROD) == "-active"
    assert state_class(SlotState.VERIFYING_PROD) == "-active"
    assert state_class(SlotState.PASS) == "-pass"
    assert state_class(SlotState.FAIL) == "-fail"


def test_port_row_label_unarmed():
    row = port_row_label("COM3", present=True, view=None)
    assert row.startswith("[ ]")
    assert "COM3" in row
    assert "present" in row
    assert "--" in row


def test_port_row_label_armed_present():
    row = port_row_label("COM3", present=True, view=_view(SlotState.FLASHING_TEST))
    assert row.startswith("[x]")
    assert "present" in row
    assert "FLASH TEST" in row


def test_port_row_label_armed_absent():
    row = port_row_label("COM3", present=False, view=_view(SlotState.ARMED, present=False))
    assert row.startswith("[x]")
    assert "no board" in row
    assert "WAITING" in row
