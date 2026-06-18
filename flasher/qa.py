"""QA traceability CSV writer with a background write queue."""

from __future__ import annotations

import csv
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import FLASHER_ROOT

DEFAULT_QA_CSV_PATH = FLASHER_ROOT / "qa-results.csv"

CSV_COLUMNS = (
    "timestamp",
    "mac_address",
    "com_port",
    "firmware_tag",
    "firmware_commit",
    "board_type",
    "overall_result",
    "boot_check",
    "get_info",
    "wifi_scan",
    "factory_reset",
    "failure_reason",
    "notes",
)


@dataclass(frozen=True)
class QaRecord:
    mac_address: str
    com_port: str
    firmware_tag: str
    firmware_commit: str
    board_type: str
    overall_result: str
    boot_check: str
    get_info: str
    wifi_scan: str
    factory_reset: str
    failure_reason: str = ""
    notes: str = ""
    timestamp: Optional[str] = None

    def row(self) -> dict[str, str]:
        ts = self.timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {
            "timestamp": ts,
            "mac_address": self.mac_address,
            "com_port": self.com_port,
            "firmware_tag": self.firmware_tag,
            "firmware_commit": self.firmware_commit,
            "board_type": self.board_type,
            "overall_result": self.overall_result,
            "boot_check": self.boot_check,
            "get_info": self.get_info,
            "wifi_scan": self.wifi_scan,
            "factory_reset": self.factory_reset,
            "failure_reason": self.failure_reason,
            "notes": self.notes,
        }


class QaCsvWriter:
    """Append QA rows sequentially via an in-memory queue."""

    def __init__(self, path: Path = DEFAULT_QA_CSV_PATH) -> None:
        self.path = path
        self._queue: queue.Queue[Optional[QaRecord]] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="qa-csv-writer", daemon=True)
        self._thread.start()

    def enqueue(self, record: QaRecord) -> None:
        self._queue.put(record)

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            record = self._queue.get()
            if record is None:
                return
            self._append(record)

    def _append(self, record: QaRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not self.path.is_file() or self.path.stat().st_size == 0
        with self.path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            if write_header:
                writer.writeheader()
            writer.writerow(record.row())


def record_from_production_verify(
    *,
    port: str,
    board_type: str,
    firmware_tag: str,
    result: object,
) -> QaRecord:
    """Build a CSV row from a :class:`~flasher.verify.ProductionVerifyResult`."""
    from .verify import ProductionVerifyResult, StepResult, Verdict

    if not isinstance(result, ProductionVerifyResult):
        raise TypeError("result must be a ProductionVerifyResult")

    def step_name(step: StepResult) -> str:
        return step.value

    overall = "PASS" if result.verdict is Verdict.PASS else "FAIL"
    return QaRecord(
        mac_address=result.mac_address or "",
        com_port=port,
        firmware_tag=firmware_tag,
        firmware_commit=result.firmware_commit,
        board_type=board_type,
        overall_result=overall,
        boot_check=step_name(result.boot_check),
        get_info=step_name(result.get_info),
        wifi_scan=step_name(result.wifi_scan),
        factory_reset=step_name(result.factory_reset),
        failure_reason=result.failure_reason,
    )
