"""One-time firmware builds via PlatformIO.

Both the production image and each verification probe are built once at startup
and cached as ``.bin`` files, so per-board flashing afterwards is pure esptool
and safe to run in parallel across ports.

Production firmware is built from a tagged checkout of SlimeVR-Tracker-ESP.
Verification probes live in this repository under ``probes/`` and link against
that firmware tree via ``platformio.nodemcu.integration.ini``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import FLASHER_ROOT, BoardConfig
from .firmware import PROBE_INI_NAME, ensure_firmware

INTEGRATION_ENV = "integration_nodemcu_probe"
INTEGRATION_SRC_DIR = "probes"
CACHE_DIR = FLASHER_ROOT / ".cache" / "bins"

LineSink = Optional[Callable[[str], None]]


class BuildError(RuntimeError):
    """Raised when a PlatformIO build fails or produces no firmware."""


@dataclass(frozen=True)
class BuildArtifacts:
    """Cached firmware images produced at startup."""

    production: Path
    tests: list[tuple[str, Path]]
    firmware_tag: str


def _pio() -> str:
    pio = shutil.which("pio")
    if pio is None:
        raise BuildError(
            "Could not find 'pio' on PATH. Install PlatformIO "
            "(pip install platformio) or activate its environment."
        )
    return pio


def _run_pio(
    args: list[str],
    cwd: Path,
    env_overrides: dict[str, str],
    on_line: LineSink,
) -> None:
    cmd = [_pio(), *args]
    if on_line:
        on_line("$ " + " ".join(cmd))
    env = dict(os.environ)
    env.update(env_overrides)
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    proc.wait()
    if proc.returncode != 0:
        raise BuildError(
            f"PlatformIO build failed (exit {proc.returncode}): {' '.join(cmd)}"
        )


def _firmware_bin(project_root: Path, env: str) -> Path:
    return project_root / ".pio" / "build" / env / "firmware.bin"


def _src_filter_for(test_src: str) -> str:
    """Build-src filter relative to the integration src_dir (``probes/``)."""
    rel = test_src
    prefix = INTEGRATION_SRC_DIR.rstrip("/") + "/"
    if rel.startswith(prefix):
        rel = rel[len(prefix) :]
    return f"+<{rel}>"


def _cache_name_for(test_src: str) -> str:
    return f"test_{Path(test_src).stem}.bin"


def _cache(src: Path, name: str) -> Path:
    if not src.is_file():
        raise BuildError(f"Expected firmware not found: {src}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dst = CACHE_DIR / name
    shutil.copy2(src, dst)
    return dst


def _production_env_overrides(config: BoardConfig) -> dict[str, str]:
    return {
        "SLIMEVR_OVERRIDE_DEFAULTS": json.dumps(config.values),
        "PLATFORMIO_BUILD_FLAGS": config.branding_build_flags,
    }


def build_production(
    config: BoardConfig,
    firmware_root: Path,
    on_line: LineSink = None,
) -> Path:
    """Build the shippable firmware from the config values and cache it."""
    _run_pio(
        ["run", "-e", config.board_type],
        firmware_root,
        _production_env_overrides(config),
        on_line,
    )
    return _cache(_firmware_bin(firmware_root, config.board_type), "production.bin")


def build_test(
    config: BoardConfig,
    test_src: str,
    firmware_root: Path,
    on_line: LineSink = None,
) -> Path:
    """Build a single verification probe and cache it."""
    overrides = {
        "SLIMEVR_OVERRIDE_DEFAULTS": json.dumps(config.values),
        "PLATFORMIO_BUILD_SRC_FILTER": _src_filter_for(test_src),
    }
    _run_pio(
        ["run", "-c", PROBE_INI_NAME, "-e", INTEGRATION_ENV],
        firmware_root,
        overrides,
        on_line,
    )
    # The integration env reuses one output dir, so cache immediately after each build.
    return _cache(
        _firmware_bin(firmware_root, INTEGRATION_ENV),
        _cache_name_for(test_src),
    )


def build_all(
    config: BoardConfig,
    on_line: LineSink = None,
    *,
    firmware_repo: str | None = None,
    firmware_tag: str | None = None,
) -> BuildArtifacts:
    """Build the production image and every verification probe, in order."""
    repo_url = firmware_repo or None
    kwargs: dict = {"on_line": on_line}
    if repo_url is not None:
        kwargs["repo_url"] = repo_url
    if firmware_tag is not None:
        kwargs["tag"] = firmware_tag
    firmware_root, tag = ensure_firmware(**kwargs)
    production = build_production(config, firmware_root, on_line)
    tests = [(t, build_test(config, t, firmware_root, on_line)) for t in config.tests]
    return BuildArtifacts(production=production, tests=tests, firmware_tag=tag)
