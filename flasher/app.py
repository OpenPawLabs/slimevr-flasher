"""Textual TUI for the SlimeVR PCBA flashing tool.

Flow: build production + verification firmware once (worker thread), then poll
serial ports. The UI splits into two panels:

* Control ("Ports"): every detected (or armed-but-unplugged) port as a row you
  highlight and toggle to arm/disarm it.
* Status: one larger, color-coded :class:`~.widgets.SlotCard` per armed port,
  showing live progress (blue while flashing/verifying, green PASS, red FAIL).

A collapsed-by-default log (auto-expanded during the build and on failures)
shows build output and per-port verification serial. The UI is driven by one
timer that reads plain state mutated by worker threads, so no widget is ever
touched off the main loop.
"""

from __future__ import annotations

import argparse
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import (
    Collapsible,
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from . import builder, ports, verify
from .config import ConfigError, load_board_config
from .qa import QaCsvWriter, record_from_production_verify
from .slot import Slot, SlotState
from .widgets import SlotCard, port_row_label

_REFRESH_INTERVAL = 0.3
_IDLE_STATES = frozenset({SlotState.ARMED, SlotState.PASS, SlotState.FAIL})


class FlasherApp(App):
    CSS = """
    #status { padding: 0 1; height: auto; color: $text-muted; }
    #stats { height: auto; padding: 0 1; border: round $panel; text-style: bold; }
    #ports { height: auto; max-height: 10; border: round $panel; padding: 0 1; }
    #status_cards { height: 1fr; border: round $panel; padding: 1 1 0 1; }
    #summary { padding: 0 1; height: auto; text-style: bold; }
    #log { height: 12; background: $surface; }

    SlotCard { height: auto; border: round $panel; background: $panel; padding: 0 1; margin: 0 0 1 0; }
    SlotCard .slot-header { text-style: bold; width: 1fr; }
    SlotCard .slot-detail { color: $text-muted; }
    SlotCard .slot-row { height: 1; }
    SlotCard .slot-tag { width: 8; color: $text-muted; }
    SlotCard ProgressBar { width: 1fr; }

    SlotCard.-idle { border: round $panel-lighten-2; }
    SlotCard.-idle .slot-header { color: $text-muted; }
    SlotCard.-active { border: round $primary; background: $primary 30%; }
    SlotCard.-active .slot-header { color: $primary; }
    SlotCard.-pass { border: round $success; background: $success 30%; }
    SlotCard.-pass .slot-header { color: $success; }
    SlotCard.-fail { border: round $error; background: $error 30%; }
    SlotCard.-fail .slot-header { color: $error; }
    """

    BINDINGS = [
        ("a", "arm_all", "Arm all detected"),
        ("d", "disarm_idle", "Disarm idle"),
        ("l", "toggle_log", "Toggle log"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config,
        *,
        firmware_repo: str | None = None,
        firmware_tag: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._firmware_repo = firmware_repo
        self._firmware_tag = firmware_tag
        self.slots: dict[str, Slot] = {}

        self._detected: set[str] = set()
        self._candidate_ports: set[str] = set()
        self._port_items: dict[str, ListItem] = {}
        self._port_labels: dict[str, Label] = {}
        self._cards: dict[str, SlotCard] = {}
        self._prev_fails: set[str] = set()

        # Session statistics, tallied as runs complete (survives disarm).
        self._stats_lock = threading.Lock()
        self._n_total = 0
        self._n_pass = 0
        self._n_fail = 0

        self._artifacts: Optional[builder.BuildArtifacts] = None
        self._build_error: Optional[str] = None
        self._build_lines: deque[str] = deque(maxlen=2000)
        self._log_total = 0
        self._log_written = 0
        self._build_lock = threading.Lock()
        # NB: avoid the name `_ready`; Textual's App has an internal `_ready()` coroutine.
        self._build_ready = False
        self._qa_writer = QaCsvWriter()

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("Starting...", id="status")
        yield Static("", id="stats")
        yield ListView(id="ports")
        yield VerticalScroll(id="status_cards")
        yield Static("", id="summary")
        with Collapsible(title="Log", collapsed=True, id="log_panel"):
            yield RichLog(id="log", wrap=True, highlight=False, markup=False, max_lines=2000)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#stats", Static).border_title = "Session"
        self.query_one("#ports", ListView).border_title = "Ports (Enter/click toggles)"
        self.query_one("#status_cards", VerticalScroll).border_title = "Status"
        self._refresh_stats()
        self.run_worker(self._build, thread=True, exclusive=True, name="build")
        self.set_interval(_REFRESH_INTERVAL, self._tick)

    # -- build worker ------------------------------------------------------

    def _build(self) -> None:
        try:
            artifacts = builder.build_all(
                self.config,
                on_line=self._log,
                firmware_repo=self._firmware_repo,
                firmware_tag=self._firmware_tag,
            )
        except Exception as exc:  # BuildError or anything unexpected
            with self._build_lock:
                self._build_error = str(exc)
            return
        with self._build_lock:
            self._artifacts = artifacts

    def _log(self, line: str) -> None:
        with self._build_lock:
            self._build_lines.append(line)
            self._log_total += 1

    def _tee(self, port: str, inner):
        """Wrap a slot's serial callback to also mirror lines into the shared log."""

        def cb(line: str) -> None:
            if inner is not None:
                inner(line)
            self._log(f"[{port}] {line}")

        return cb

    # -- timer-driven refresh ---------------------------------------------

    def _tick(self) -> None:
        self._flush_log()
        self._refresh_stats()
        if not self._build_ready:
            self._refresh_build_status()
            if not self._build_ready:
                return
        self._poll_ports()
        views = {port: slot.snapshot() for port, slot in self.slots.items()}
        self._refresh_ports_list(views)
        self._refresh_cards(views)
        self._refresh_summary(views)
        self._handle_failures(views)

    def _flush_log(self) -> None:
        with self._build_lock:
            pending = self._log_total - self._log_written
            if pending <= 0:
                return
            pending = min(pending, len(self._build_lines))
            new = list(self._build_lines)[-pending:]
            self._log_written = self._log_total
        log = self.query_one("#log", RichLog)
        for line in new:
            log.write(line)

    def _refresh_build_status(self) -> None:
        with self._build_lock:
            error = self._build_error
            artifacts = self._artifacts
        status = self.query_one("#status", Static)
        panel = self.query_one("#log_panel", Collapsible)
        if error is not None:
            status.update(f"Build failed: {error}")
            panel.collapsed = False
        elif artifacts is not None:
            self._build_ready = True
            n = len(artifacts.tests)
            status.update(
                f"Ready. Built production + {n} test image(s) for {self.config.board_type}. "
                "Arm a detected port to flash boards."
            )
            panel.collapsed = True
        else:
            status.update(f"Building firmware for {self.config.board_type}...")
            panel.collapsed = False

    def _poll_ports(self) -> None:
        current = ports.list_serial_ports()
        for port, slot in self.slots.items():
            slot.set_present(port in current)
        self._detected = current
        self._candidate_ports = current - set(self.slots)

    def _refresh_ports_list(self, views) -> None:
        listview = self.query_one("#ports", ListView)
        shown = sorted(self._detected | set(self.slots))
        for port in list(self._port_items):
            if port not in shown:
                self._port_items.pop(port).remove()
                self._port_labels.pop(port, None)
        for port in shown:
            present = port in self._detected
            text = port_row_label(port, present, views.get(port))
            if port not in self._port_items:
                label = Label(text)
                item = ListItem(label, name=port)
                self._port_items[port] = item
                self._port_labels[port] = label
                listview.append(item)
            else:
                self._port_labels[port].update(text)

    def _refresh_cards(self, views) -> None:
        container = self.query_one("#status_cards", VerticalScroll)
        for port in list(self._cards):
            if port not in self.slots:
                self._cards.pop(port).remove()
        for port in sorted(self.slots):
            card = self._cards.get(port)
            if card is None:
                card = SlotCard(views[port])
                self._cards[port] = card
                container.mount(card)
            else:
                card.update_view(views[port])

    def _refresh_summary(self, views) -> None:
        passed = sum(1 for v in views.values() if v.state is SlotState.PASS)
        failed = sum(1 for v in views.values() if v.state is SlotState.FAIL)
        active = sum(1 for v in views.values() if v.state not in _IDLE_STATES)
        self.query_one("#summary", Static).update(
            f"Slots: {len(views)}   Active: {active}   Pass: {passed}   Fail: {failed}"
        )

    def _handle_failures(self, views) -> None:
        fails = {port for port, v in views.items() if v.state is SlotState.FAIL}
        if fails - self._prev_fails:  # a new failure: surface the log
            self.query_one("#log_panel", Collapsible).collapsed = False
        self._prev_fails = fails

    def _refresh_stats(self) -> None:
        with self._stats_lock:
            total, passed, failed = self._n_total, self._n_pass, self._n_fail
        self.query_one("#stats", Static).update(
            f"Flashed: {total}    [green]Pass: {passed}[/]    [red]Fail: {failed}[/]"
        )

    def _record_result(self, ok: bool) -> None:
        """Tally a completed run (called from a slot's worker thread)."""
        with self._stats_lock:
            self._n_total += 1
            if ok:
                self._n_pass += 1
            else:
                self._n_fail += 1

    # -- arm / disarm ------------------------------------------------------

    def _arm(self, port: str) -> None:
        if not self._build_ready or self._artifacts is None or port in self.slots:
            return
        slot = Slot(
            port,
            self._artifacts,
            verify_fn=self._make_verify_fn(),
            verify_prod_fn=self._make_verify_prod_fn(),
            on_result=self._record_result,
            on_qa_record=self._record_qa,
        )
        self.slots[port] = slot
        slot.set_present(port in self._detected)
        self._candidate_ports.discard(port)

    def _disarm(self, port: str) -> None:
        slot = self.slots.get(port)
        if slot is None:
            return
        if slot.snapshot().state in _IDLE_STATES:
            del self.slots[port]
        else:
            self.query_one("#status", Static).update(
                f"{port}: can't disarm while flashing; wait for it to finish."
            )

    def _make_verify_fn(self):
        def verify_fn(port, on_line):
            return verify.monitor(port, on_line=self._tee(port, on_line))

        return verify_fn

    def _make_verify_prod_fn(self):
        pv = self.config.production_verify
        if pv is None:
            return None

        def verify_prod_fn(port, on_line):
            return verify.monitor_production_suite(
                port, pv, on_line=self._tee(port, on_line)
            )

        return verify_prod_fn

    def _record_qa(self, port, result, artifacts) -> None:
        """Enqueue a QA CSV row (called from a slot worker thread)."""
        self._qa_writer.enqueue(
            record_from_production_verify(
                port=port,
                board_type=self.config.board_type,
                firmware_tag=artifacts.firmware_tag,
                result=result,
            )
        )

    # -- events / actions --------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        port = event.item.name
        if not port:
            return
        if port in self.slots:
            self._disarm(port)
        else:
            self._arm(port)

    def action_arm_all(self) -> None:
        for port in sorted(self._candidate_ports):
            self._arm(port)

    def action_disarm_idle(self) -> None:
        for port, slot in list(self.slots.items()):
            if slot.snapshot().state in _IDLE_STATES:
                del self.slots[port]

    def action_toggle_log(self) -> None:
        panel = self.query_one("#log_panel", Collapsible)
        panel.collapsed = not panel.collapsed


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m flasher",
        description="Mass-flash and verify SlimeVR PCBA boards.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to board-config.json (defaults to config/board-config.json).",
    )
    parser.add_argument(
        "--firmware-repo",
        default=None,
        help=(
            "Git URL for SlimeVR-Tracker-ESP (default: "
            "https://github.com/SlimeVR/SlimeVR-Tracker-ESP.git)."
        ),
    )
    parser.add_argument(
        "--firmware-tag",
        default=None,
        help="Firmware release tag to build (default: latest upstream tag).",
    )
    args = parser.parse_args(argv)

    try:
        config = load_board_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error:\n{exc}")
        return 2

    FlasherApp(
        config,
        firmware_repo=args.firmware_repo,
        firmware_tag=args.firmware_tag,
    ).run()
    return 0
