#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload and optionally monitor a manual hardware integration test."
    )
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port for upload and monitor, for example COM4 or /dev/ttyUSB0.",
    )
    parser.add_argument(
        "--test-src",
        required=True,
        help=(
            "Test source path relative to probes/, "
            "for example: --test-src imu/lsm6dsv/lsm6dsv_smoke_test.cpp"
        ),
    )
    parser.add_argument(
        "--build-src-filter",
        help=(
            "Optional raw PlatformIO build_src_filter override, "
            "for example '+<mag/bmm350/bmm350_lsm6dsv_bringup.cpp>'. "
            "When omitted, --test-src is used."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "PlatformIO config file inside the cached firmware checkout "
            "(default: platformio.nodemcu.probe.ini)."
        ),
    )
    parser.add_argument(
        "--monitor-baud",
        type=int,
        default=115200,
        help="Serial monitor baud rate.",
    )
    parser.add_argument(
        "--monitor-filters",
        default="direct",
        help="PlatformIO monitor filters.",
    )
    parser.add_argument(
        "--monitor-delay-seconds",
        type=float,
        default=1.0,
        help="Delay before attaching the serial monitor after upload.",
    )
    parser.add_argument(
        "--no-monitor",
        action="store_true",
        help="Upload the test firmware without starting a serial monitor.",
    )
    parser.add_argument(
        "--monitor-timeout-seconds",
        type=float,
        default=10.0,
        help=(
            "Maximum monitor runtime before auto-closing the serial session. "
            "Set to 0 or a negative value to disable timeout."
        ),
    )
    return parser.parse_args()


def run_command(
    command: list[str], project_root: Path, env_overrides: dict[str, str] | None = None
) -> int:
    print(f"$ {' '.join(command)}")
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(command, cwd=project_root, env=env)
    return result.returncode


def run_monitor_with_timeout(
    command: list[str], project_root: Path, timeout_seconds: float
) -> int:
    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    test_end_marker = "[TEST_END]"
    deadline = (
        time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    )
    try:
        if process.stdout is None:
            process.wait(timeout=timeout_seconds if timeout_seconds > 0 else None)
            return process.returncode

        for line in process.stdout:
            print(line, end="")
            if test_end_marker in line:
                print("[INFO] Detected [TEST_END]. Closing serial monitor.")
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 0

            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(command, timeout_seconds)

        process.wait()
        return process.returncode
    except subprocess.TimeoutExpired:
        print(
            f"[INFO] Monitor timeout reached ({timeout_seconds:.1f}s). Closing serial monitor."
        )
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 0
    except KeyboardInterrupt:
        print("[INFO] Monitor interrupted by user. Closing serial monitor.")
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 130


def main() -> int:
    args = parse_args()
    flasher_root = Path(__file__).resolve().parents[1]
    pio_path = shutil.which("pio")

    if pio_path is None:
        print(
            "Could not find 'pio' on PATH. Install PlatformIO or activate the environment that provides it.",
            file=sys.stderr,
        )
        return 1

    from flasher.firmware import PROBE_INI_NAME, ensure_firmware

    try:
        firmware_root, _tag = ensure_firmware()
    except Exception as exc:
        print(f"Failed to fetch firmware sources: {exc}", file=sys.stderr)
        return 1

    config_name = args.config or PROBE_INI_NAME
    config_path = firmware_root / config_name
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    test_path = flasher_root / "probes" / args.test_src
    if not test_path.exists() and args.build_src_filter is None:
        print(f"Test source not found: {test_path}", file=sys.stderr)
        return 1

    build_src_filter = args.build_src_filter
    if build_src_filter is None:
        build_src_filter = f"+<{args.test_src}>"

    upload_command = [
        pio_path,
        "run",
        "-c",
        config_name,
        "-e",
        "integration_nodemcu_probe",
        "-t",
        "upload",
        "--upload-port",
        args.port,
    ]
    exit_code = run_command(
        upload_command,
        firmware_root,
        env_overrides={"PLATFORMIO_BUILD_SRC_FILTER": build_src_filter},
    )
    if exit_code != 0:
        return exit_code

    if args.no_monitor:
        return 0

    time.sleep(max(args.monitor_delay_seconds, 0.0))

    monitor_command = [
        pio_path,
        "device",
        "monitor",
        "-p",
        args.port,
        "-b",
        str(args.monitor_baud),
        "--filter",
        args.monitor_filters,
    ]
    return run_monitor_with_timeout(
        monitor_command, flasher_root, args.monitor_timeout_seconds
    )


if __name__ == "__main__":
    raise SystemExit(main())
