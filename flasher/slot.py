"""Per-port flashing slot: a small state machine driven by a worker thread.

Each armed port owns a :class:`Slot`. When a board is present, the slot runs the
verify-then-ship pipeline in its own thread, so multiple slots flash in parallel:

    ARMED -> FLASHING_TEST -> VERIFYING -> (repeat per test)
          -> FLASHING_PROD -> VERIFYING_PROD
          -> PASS | FAIL -> (await unplug) -> ARMED

A board only reaches production flashing if every verification probe passes, and
only reaches PASS if the shipped firmware then boots cleanly (VERIFYING_PROD,
when production checks are configured). The pipeline is divided into equal-weight
stages so an overall 0-100 progress can be reported; within a flashing stage the
esptool percentage fills that stage's slice smoothly.

After a terminal result the slot waits for the board to be unplugged before it
will flash the next one (re-arm requires unplug/replug).

Hardware access is injected (``flash_fn`` / ``verify_fn`` / ``verify_prod_fn``)
so the state machine is fully unit-testable without real devices.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from .builder import BuildArtifacts


class SlotState(str, Enum):
    ARMED = "armed"
    FLASHING_TEST = "flashing-test"
    VERIFYING = "verifying"
    FLASHING_PROD = "flashing-prod"
    VERIFYING_PROD = "verifying-prod"
    PASS = "pass"
    FAIL = "fail"


TERMINAL_STATES = frozenset({SlotState.PASS, SlotState.FAIL})

# flash_fn(port, bin_path, on_progress, on_line) -> result with `.ok`
FlashFn = Callable[..., object]
# verify_fn(port, on_line) -> result with `.passed` and `.verdict`
VerifyFn = Callable[..., object]
# on_result(ok) -> None, fired once per completed run (for session statistics)
ResultCb = Optional[Callable[[bool], None]]
# on_qa_record(port, verify_result, artifacts) -> None after production verification
QaRecordCb = Optional[Callable[..., None]]

_UNSET = object()


@dataclass(frozen=True)
class SlotView:
    """Immutable snapshot of slot state for rendering."""

    port: str
    state: SlotState
    progress: int  # current stage's flash percentage (0-100)
    overall: int  # whole-pipeline progress (0-100)
    message: str
    current_test: Optional[str]
    present: bool


class Slot:
    def __init__(
        self,
        port: str,
        artifacts: BuildArtifacts,
        *,
        flash_fn: Optional[FlashFn] = None,
        verify_fn: Optional[VerifyFn] = None,
        verify_prod_fn: Optional[VerifyFn] = None,
        on_result: ResultCb = None,
        on_qa_record: QaRecordCb = None,
    ) -> None:
        self.port = port
        self.artifacts = artifacts
        self._flash = flash_fn or _default_flash
        self._verify = verify_fn or _default_verify
        self._verify_prod = verify_prod_fn  # None -> skip production verification
        self._on_result = on_result
        self._on_qa_record = on_qa_record

        self.state = SlotState.ARMED
        self.progress = 0
        self.overall = 0
        self.message = "Waiting for board"
        self.current_test: Optional[str] = None
        self.present = False
        self.log: list[str] = []

        self._total_stages = 1
        self._completed = 0
        self._flash_frac = 0.0

        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # -- external events ---------------------------------------------------

    def set_present(self, present: bool) -> None:
        """Update board presence; start or re-arm the pipeline accordingly."""
        with self._lock:
            self.present = present
            terminal = self.state in TERMINAL_STATES
        if present:
            self.maybe_start()
        elif terminal:
            self._reset_armed()

    def maybe_start(self) -> None:
        """Start the pipeline if the slot is idle, armed, and a board is present."""
        with self._lock:
            if self.state is not SlotState.ARMED or not self.present:
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run_pipeline, name=f"slot-{self.port}", daemon=True
            )
            thread = self._thread
        thread.start()

    def wait(self, timeout: Optional[float] = None) -> None:
        """Join the worker thread (used by tests)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def snapshot(self) -> SlotView:
        with self._lock:
            return SlotView(
                port=self.port,
                state=self.state,
                progress=self.progress,
                overall=self.overall,
                message=self.message,
                current_test=self.current_test,
                present=self.present,
            )

    # -- pipeline ----------------------------------------------------------

    def _run_pipeline(self) -> None:
        try:
            with self._lock:
                self._completed = 0
                self._flash_frac = 0.0
                self._total_stages = (
                    len(self.artifacts.tests) * 2
                    + 1
                    + (1 if self._verify_prod is not None else 0)
                )

            for test_src, test_bin in self.artifacts.tests:
                name = Path(test_src).name
                self._begin_stage(
                    SlotState.FLASHING_TEST, f"Flashing test: {name}", current_test=test_src
                )
                if not self._flash(self.port, test_bin, self._on_progress, self._on_line).ok:
                    self._finish(False, f"Test flash failed: {name}")
                    return
                self._complete_stage()

                self._begin_stage(SlotState.VERIFYING, f"Verifying: {name}")
                result = self._verify(self.port, self._on_line)
                if not result.passed:
                    self._finish(False, f"Verify {result.verdict.value}: {name}")
                    return
                self._complete_stage()

            self._begin_stage(
                SlotState.FLASHING_PROD, "Flashing production firmware", current_test=None
            )
            if not self._flash(
                self.port, self.artifacts.production, self._on_progress, self._on_line
            ).ok:
                self._finish(False, "Production flash failed")
                return
            self._complete_stage()

            if self._verify_prod is not None:
                self._begin_stage(SlotState.VERIFYING_PROD, "Verifying production firmware")
                result = self._verify_prod(self.port, self._on_line)
                if self._on_qa_record is not None:
                    self._on_qa_record(self.port, result, self.artifacts)
                if not result.passed:
                    detail = getattr(result, "failure_reason", "") or result.verdict.value
                    self._finish(False, f"Production verify failed: {detail}")
                    return
                self._complete_stage()

            self._finish(True, "Verified and shipped")
        except Exception as exc:  # surface any unexpected failure as FAIL
            self._on_line(f"[error] {exc}")
            self._finish(False, f"Error: {exc}")

    # -- stage / progress bookkeeping --------------------------------------

    def _begin_stage(
        self, state: SlotState, message: str, *, current_test: object = _UNSET
    ) -> None:
        with self._lock:
            self.state = state
            self.message = message
            self.progress = 0
            self._flash_frac = 0.0
            if current_test is not _UNSET:
                self.current_test = current_test  # type: ignore[assignment]
            self.overall = self._overall_locked()

    def _complete_stage(self) -> None:
        with self._lock:
            self._completed += 1
            self._flash_frac = 0.0
            self.progress = 100
            self.overall = self._overall_locked()

    def _overall_locked(self) -> int:
        if self._total_stages <= 0:
            return 0
        value = (self._completed + self._flash_frac) / self._total_stages * 100
        return max(0, min(100, round(value)))

    def _finish(self, ok: bool, message: str) -> None:
        with self._lock:
            self.state = SlotState.PASS if ok else SlotState.FAIL
            self.progress = 100
            self.message = message
            self.current_test = None
            if ok:
                self.overall = 100
        if self._on_result is not None:
            self._on_result(ok)
        # If the board was unplugged mid-run, re-arm right away for the next one.
        with self._lock:
            present = self.present
        if not present:
            self._reset_armed()

    def _reset_armed(self) -> None:
        with self._lock:
            self.state = SlotState.ARMED
            self.progress = 0
            self.overall = 0
            self.message = "Waiting for board"
            self.current_test = None
            self._completed = 0
            self._flash_frac = 0.0

    # -- callbacks ---------------------------------------------------------

    def _on_progress(self, pct: int) -> None:
        with self._lock:
            self.progress = max(0, min(100, pct))
            self._flash_frac = self.progress / 100.0
            self.overall = self._overall_locked()

    def _on_line(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if len(self.log) > 200:
                del self.log[:-200]


def _default_flash(port, bin_path, on_progress, on_line):
    from . import flash as flash_mod

    return flash_mod.flash(port, bin_path, on_progress=on_progress, on_line=on_line)


def _default_verify(port, on_line):
    from . import verify as verify_mod

    return verify_mod.monitor(port, on_line=on_line)
