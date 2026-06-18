"""Serial-based board verification.

Two verification modes share serial I/O helpers:

* Probe verification (:func:`monitor`): a flashed integration probe prints a
  verdict; PASS only if ``[VERIFY_PASS]`` is seen before ``[TEST_END]``.
* Production verification (:func:`monitor_production_suite`): after the
  shippable firmware is flashed, wait for boot, run ``GET INFO`` / ``GET
  WIFISCAN`` / ``FRST``, and confirm a clean reboot.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterator, Optional, Sequence

from .config import ProductionVerifyConfig

PASS_MARKER = "[VERIFY_PASS]"
FAIL_MARKER = "[VERIFY_FAIL]"
END_MARKER = "[TEST_END]"

LineCb = Optional[Callable[[str], None]]

MAC_RE = re.compile(r"mac:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
SENSOR0_RE = re.compile(
    r"Sensor\[0\]:\s*(\S+)\s+\([^)]+\)\s+is working:\s*(true|false),\s*had data:\s*(true|false)"
)
GIT_COMMIT_RE = re.compile(r"Git commit:\s*(\S+)")
WSCAN_FOUND_RE = re.compile(r"\[WSCAN\]\s+Found\s+(\d+)\s+networks:")
WSCAN_FAILED_RE = re.compile(r"\[WSCAN\]\s+Scan failed!")


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"


class StepResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class VerifyResult:
    verdict: Verdict
    lines: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS


@dataclass
class ProductionVerifyResult:
    verdict: Verdict
    lines: list[str] = field(default_factory=list)
    mac_address: str = ""
    firmware_commit: str = ""
    boot_check: StepResult = StepResult.SKIP
    get_info: StepResult = StepResult.SKIP
    wifi_scan: StepResult = StepResult.SKIP
    factory_reset: StepResult = StepResult.SKIP
    failure_reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.PASS


def evaluate(lines: Sequence[str]) -> Verdict:
    """Decide a probe verdict from captured serial lines."""
    saw_pass = False
    for line in lines:
        if FAIL_MARKER in line:
            return Verdict.FAIL
        if PASS_MARKER in line:
            saw_pass = True
        if END_MARKER in line:
            return Verdict.PASS if saw_pass else Verdict.FAIL
    return Verdict.TIMEOUT


def all_fragments_seen(lines: Sequence[str], fragments: Sequence[str]) -> bool:
    """True when every required fragment appears in at least one captured line."""
    return all(any(frag in line for line in lines) for frag in fragments)


def parse_mac(lines: Sequence[str]) -> str | None:
    for line in lines:
        match = MAC_RE.search(line)
        if match:
            return match.group(1).upper()
    return None


def parse_git_commit(lines: Sequence[str]) -> str | None:
    for line in lines:
        match = GIT_COMMIT_RE.search(line)
        if match:
            return match.group(1)
    return None


def parse_sensor0(lines: Sequence[str]) -> tuple[str, bool, bool] | None:
    for line in lines:
        match = SENSOR0_RE.search(line)
        if match:
            imu, working, had_data = match.groups()
            return imu, working == "true", had_data == "true"
    return None


def parse_wifi_network_count(lines: Sequence[str]) -> int | None:
    for line in lines:
        if WSCAN_FAILED_RE.search(line):
            return -1
        match = WSCAN_FOUND_RE.search(line)
        if match:
            return int(match.group(1))
    return None


def validate_get_info(
    lines: Sequence[str], *, expected_imu: str
) -> tuple[bool, str, str, str]:
    """Return (ok, mac, commit, failure_reason)."""
    mac = parse_mac(lines)
    if not mac:
        return False, "", "", "GET INFO: no MAC address in response"

    sensor = parse_sensor0(lines)
    if sensor is None:
        return False, mac, "", "GET INFO: Sensor[0] line not found"
    imu, working, had_data = sensor
    if imu != expected_imu:
        return False, mac, "", f"GET INFO: Sensor[0] is {imu}, expected {expected_imu}"
    if not working:
        return False, mac, "", "GET INFO: Sensor[0] is not working"
    if not had_data:
        return False, mac, "", "GET INFO: Sensor[0] had no data"

    commit = parse_git_commit(lines) or ""
    return True, mac, commit, ""


def validate_wifi_scan(lines: Sequence[str], *, min_networks: int) -> tuple[bool, str]:
    count = parse_wifi_network_count(lines)
    if count is None:
        return False, "GET WIFISCAN: no scan result in response"
    if count < 0:
        return False, "GET WIFISCAN: scan failed"
    if count < min_networks:
        return (
            False,
            f"GET WIFISCAN: found {count} networks, need at least {min_networks}",
        )
    return True, ""


def _read_lines(
    ser,
    deadline: float,
    on_line: LineCb,
) -> Iterator[str]:
    buffer = b""
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if not chunk:
            continue
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            text = raw.decode("utf-8", errors="replace").rstrip("\r")
            if on_line:
                on_line(text)
            yield text


def _wait_for_fragments(
    ser,
    fragments: Sequence[str],
    timeout: float,
    on_line: LineCb,
    lines: list[str],
) -> bool:
    if not fragments:
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for text in _read_lines(ser, deadline, on_line):
            lines.append(text)
            if all_fragments_seen(lines, fragments):
                return True
    return all_fragments_seen(lines, fragments)


def _send_command(ser, command: str) -> None:
    ser.write(f"{command}\r\n".encode("ascii"))
    ser.flush()


def _collect_until(
    ser,
    timeout: float,
    on_line: LineCb,
    lines: list[str],
    *,
    done: Callable[[list[str]], bool],
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for text in _read_lines(ser, deadline, on_line):
            lines.append(text)
            if done(lines):
                return


def monitor(
    port: str,
    *,
    baud: int = 115200,
    timeout: float = 20.0,
    on_line: LineCb = None,
) -> VerifyResult:
    """Read serial output until ``[TEST_END]`` or ``timeout`` (probe verdict)."""
    import serial

    lines: list[str] = []
    try:
        with serial.Serial(port, baudrate=baud, timeout=0.5) as ser:
            deadline = time.monotonic() + timeout
            for text in _read_lines(ser, deadline, on_line):
                lines.append(text)
                if END_MARKER in text:
                    return VerifyResult(evaluate(lines), lines)
    except serial.SerialException as exc:
        if on_line:
            on_line(f"[serial error] {exc}")
        return VerifyResult(Verdict.FAIL, lines)
    return VerifyResult(evaluate(lines), lines)


def monitor_production_suite(
    port: str,
    config: ProductionVerifyConfig,
    *,
    baud: int = 115200,
    on_line: LineCb = None,
) -> ProductionVerifyResult:
    """Run interactive production verification after firmware flash."""
    import serial

    lines: list[str] = []
    result = ProductionVerifyResult(Verdict.FAIL, lines)

    try:
        with serial.Serial(port, baudrate=baud, timeout=0.5) as ser:
            # Phase 1: initial boot
            if not _wait_for_fragments(
                ser,
                config.boot_fragments,
                config.boot_timeout_seconds,
                on_line,
                lines,
            ):
                result.boot_check = StepResult.FAIL
                result.failure_reason = "Boot: required fragments not seen"
                result.verdict = Verdict.TIMEOUT
                return result
            result.boot_check = StepResult.PASS

            time.sleep(config.post_boot_delay_seconds)

            # Phase 2: GET INFO
            _send_command(ser, "GET INFO")
            info_lines: list[str] = []
            _collect_until(
                ser,
                15.0,
                on_line,
                info_lines,
                done=lambda captured: parse_git_commit(captured) is not None,
            )
            lines.extend(info_lines)
            ok, mac, commit, reason = validate_get_info(
                info_lines, expected_imu=config.expected_sensor0_imu
            )
            result.mac_address = mac
            result.firmware_commit = commit
            if not ok:
                result.get_info = StepResult.FAIL
                result.failure_reason = reason
                result.verdict = Verdict.FAIL
                return result
            result.get_info = StepResult.PASS

            # Phase 3: GET WIFISCAN
            _send_command(ser, "GET WIFISCAN")
            scan_lines: list[str] = []
            _collect_until(
                ser,
                45.0,
                on_line,
                scan_lines,
                done=lambda captured: parse_wifi_network_count(captured) is not None,
            )
            lines.extend(scan_lines)
            ok, reason = validate_wifi_scan(
                scan_lines, min_networks=config.min_wifi_networks
            )
            if not ok:
                result.wifi_scan = StepResult.FAIL
                result.failure_reason = reason
                result.verdict = Verdict.FAIL
                return result
            result.wifi_scan = StepResult.PASS

            # Phase 4: factory reset and reboot
            _send_command(ser, "FRST")
            reset_lines: list[str] = []
            _collect_until(
                ser,
                10.0,
                on_line,
                reset_lines,
                done=lambda captured: any("FACTORY RESET" in line for line in captured),
            )
            lines.extend(reset_lines)

            if not _wait_for_fragments(
                ser,
                config.boot_fragments,
                config.boot_timeout_seconds + 5.0,
                on_line,
                lines,
            ):
                result.factory_reset = StepResult.FAIL
                result.failure_reason = "Factory reset: boot fragments not seen after reboot"
                result.verdict = Verdict.TIMEOUT
                return result
            result.factory_reset = StepResult.PASS
            result.verdict = Verdict.PASS
            return result

    except serial.SerialException as exc:
        if on_line:
            on_line(f"[serial error] {exc}")
        result.failure_reason = f"Serial error: {exc}"
        result.verdict = Verdict.FAIL
        return result
