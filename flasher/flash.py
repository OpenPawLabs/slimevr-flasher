"""Direct esptool flashing of a cached firmware image with progress reporting.

esptool is invoked as a subprocess (``python -m esptool``) per port, which keeps
ports fully independent and safe to flash in parallel. Flash parameters mirror
PlatformIO's defaults for the esp12e (NodeMCU) target.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

ProgressCb = Optional[Callable[[int], None]]
LineCb = Optional[Callable[[str], None]]

# esptool reports flash progress as a percentage. We accept both historical
# formats so the bar works across esptool generations:
#   4.x: "Writing at 0x0000c000... (42 %)"
#   5.x: "Writing at 0x0000c000 [===>      ]  42.3%  12345/67890 bytes..."
_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

DEFAULT_BAUD = 921600
DEFAULT_CHIP = "esp8266"
DEFAULT_FLASH_MODE = "dio"
DEFAULT_FLASH_FREQ = "40m"
APP_OFFSET = "0x0"


@dataclass(frozen=True)
class FlashResult:
    ok: bool
    returncode: int


def parse_progress(line: str) -> Optional[int]:
    """Extract a 0-100 percentage from an esptool output line, if present."""
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    return max(0, min(100, round(float(match.group(1)))))


def esptool_command(
    port: str,
    bin_path: Path | str,
    *,
    baud: int = DEFAULT_BAUD,
    chip: str = DEFAULT_CHIP,
    flash_mode: str = DEFAULT_FLASH_MODE,
    flash_freq: str = DEFAULT_FLASH_FREQ,
    app_offset: str = APP_OFFSET,
) -> list[str]:
    """Build the esptool write_flash command line."""
    return [
        sys.executable,
        "-m",
        "esptool",
        "--chip",
        chip,
        "--port",
        str(port),
        "--baud",
        str(baud),
        "--before",
        "default_reset",
        "--after",
        "hard_reset",
        "write_flash",
        "--flash_mode",
        flash_mode,
        "--flash_freq",
        flash_freq,
        "--flash_size",
        "detect",
        app_offset,
        str(bin_path),
    ]


def flash(
    port: str,
    bin_path: Path | str,
    *,
    on_progress: ProgressCb = None,
    on_line: LineCb = None,
    **command_kwargs,
) -> FlashResult:
    """Flash ``bin_path`` to ``port`` via esptool, streaming progress."""
    cmd = esptool_command(port, bin_path, **command_kwargs)
    if on_line:
        on_line("$ " + " ".join(cmd))
    # text=True enables universal-newline splitting, so esptool's carriage-return
    # progress updates surface as discrete lines.
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        if on_line:
            on_line(line)
        if on_progress:
            pct = parse_progress(line)
            if pct is not None:
                on_progress(pct)
    proc.wait()
    ok = proc.returncode == 0
    if ok and on_progress:
        on_progress(100)
    return FlashResult(ok=ok, returncode=proc.returncode)
