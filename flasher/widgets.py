"""Presentation helpers for the flasher TUI.

The state -> label/CSS-class mappings are pure functions (unit-tested without a
running app); :class:`SlotCard` is the color-coded activity card shown in the
status panel for each armed port.
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ProgressBar, Static

from .slot import SlotState, SlotView

_STATE_LABEL = {
    SlotState.ARMED: "WAITING",
    SlotState.FLASHING_TEST: "FLASH TEST",
    SlotState.VERIFYING: "VERIFYING",
    SlotState.FLASHING_PROD: "FLASH PROD",
    SlotState.VERIFYING_PROD: "VERIFY PROD",
    SlotState.PASS: "PASS",
    SlotState.FAIL: "FAIL",
}

# Card colour buckets: idle (waiting), active (flashing/verifying), pass, fail.
_STATE_CLASS = {
    SlotState.ARMED: "-idle",
    SlotState.FLASHING_TEST: "-active",
    SlotState.VERIFYING: "-active",
    SlotState.FLASHING_PROD: "-active",
    SlotState.VERIFYING_PROD: "-active",
    SlotState.PASS: "-pass",
    SlotState.FAIL: "-fail",
}

CARD_CLASSES = ("-idle", "-active", "-pass", "-fail")
_VERIFY_STATES = (SlotState.VERIFYING, SlotState.VERIFYING_PROD)


def state_label(state: SlotState) -> str:
    """Human-readable label for a slot state."""
    return _STATE_LABEL.get(state, state.value)


def state_class(state: SlotState) -> str:
    """CSS modifier class that colours a card for the given state."""
    return _STATE_CLASS.get(state, "-idle")


def port_row_label(port: str, present: bool, view: Optional[SlotView]) -> str:
    """Render a control-panel row: arm toggle, port, presence, quick state."""
    check = "[x]" if view is not None else "[ ]"
    presence = "present" if present else "no board"
    state = state_label(view.state) if view is not None else "--"
    return f"{check}  {port:<12}  {presence:<9}  {state}"


class SlotCard(Vertical):
    """A larger, color-coded activity card for one armed port."""

    def __init__(self, view: SlotView) -> None:
        super().__init__()
        self._view = view

    def compose(self) -> ComposeResult:
        yield Label("", classes="slot-header")
        with Horizontal(classes="slot-row"):
            yield Label("Overall", classes="slot-tag")
            yield ProgressBar(total=100, show_eta=False, classes="overall")
        with Horizontal(classes="slot-row"):
            yield Label("Stage", classes="slot-tag")
            yield ProgressBar(total=100, show_eta=False, classes="stage")
        yield Static("", classes="slot-detail")

    def on_mount(self) -> None:
        self.update_view(self._view)

    def update_view(self, view: SlotView) -> None:
        self._view = view
        if not self.is_mounted:
            return  # children not yet queryable; on_mount will apply this view
        active = state_class(view.state)
        for cls in CARD_CLASSES:
            self.set_class(cls == active, cls)
        self.query_one(".slot-header", Label).update(
            f"{view.port}   {state_label(view.state)}"
        )
        self.query_one(".slot-detail", Static).update(view.message)
        self.query_one(".overall", ProgressBar).update(total=100, progress=view.overall)
        stage = self.query_one(".stage", ProgressBar)
        if view.state in _VERIFY_STATES:
            stage.update(total=None)  # indeterminate pulse while reading serial
        else:
            stage.update(total=100, progress=view.progress)
