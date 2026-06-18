"""Fetch a tagged SlimeVR-Tracker-ESP firmware tree for PlatformIO builds.

Production firmware is built from a shallow clone of SlimeVR-Tracker-ESP at a
release tag (latest by default). The clone is cached under ``.cache/firmware/``
so repeat runs skip network access when the tag is unchanged.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import FLASHER_ROOT

DEFAULT_FIRMWARE_REPO = "https://github.com/SlimeVR/SlimeVR-Tracker-ESP.git"
CACHE_DIR = FLASHER_ROOT / ".cache"
FIRMWARE_DIR = CACHE_DIR / "firmware"
TAG_STAMP = CACHE_DIR / "firmware_tag.txt"
PROBE_INI_SOURCE = Path(__file__).parent / "platformio.nodemcu.integration.ini"
PROBE_INI_NAME = "platformio.nodemcu.probe.ini"

LineSink = Optional[Callable[[str], None]]

_TAG_SUFFIX_RE = re.compile(r"\^\{\}$")


class FirmwareError(RuntimeError):
    """Raised when the firmware repository cannot be resolved or checked out."""


def _git() -> str:
    git = shutil.which("git")
    if git is None:
        raise FirmwareError(
            "Could not find 'git' on PATH. Install Git to download firmware sources."
        )
    return git


def _emit(on_line: LineSink, message: str) -> None:
    if on_line:
        on_line(message)


def _run_git(args: list[str], on_line: LineSink = None) -> str:
    cmd = [_git(), *args]
    _emit(on_line, "$ " + " ".join(cmd))
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise FirmwareError(
            f"Git command failed (exit {proc.returncode}): {' '.join(cmd)}"
            + (f"\n{detail}" if detail else "")
        )
    return proc.stdout


def resolve_latest_tag(
    repo_url: str = DEFAULT_FIRMWARE_REPO, on_line: LineSink = None
) -> str:
    """Return the newest semver-like tag from ``repo_url``."""
    output = _run_git(
        ["ls-remote", "--tags", "--sort=-v:refname", repo_url],
        on_line,
    )
    for line in output.splitlines():
        if not line.strip():
            continue
        _hash, ref = line.split("\t", 1)
        tag = ref.removeprefix("refs/tags/")
        if _TAG_SUFFIX_RE.search(tag):
            continue
        return tag
    raise FirmwareError(f"No release tags found at {repo_url}")


def _cached_tag() -> Optional[str]:
    if not TAG_STAMP.is_file():
        return None
    return TAG_STAMP.read_text(encoding="utf-8").strip() or None


def _write_cached_tag(tag: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TAG_STAMP.write_text(tag + "\n", encoding="utf-8")


def _clone_firmware(
    repo_url: str, tag: str, on_line: LineSink = None
) -> None:
    if FIRMWARE_DIR.exists():
        shutil.rmtree(FIRMWARE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _run_git(
        [
            "clone",
            "--depth",
            "1",
            "--branch",
            tag,
            "--single-branch",
            repo_url,
            str(FIRMWARE_DIR),
        ],
        on_line,
    )
    if not (FIRMWARE_DIR / "platformio.ini").is_file():
        raise FirmwareError(
            f"Cloned firmware at tag {tag!r} is missing platformio.ini: {FIRMWARE_DIR}"
        )


def install_probe_ini(firmware_root: Path = FIRMWARE_DIR) -> Path:
    """Copy the probe PlatformIO config into the firmware checkout."""
    if not PROBE_INI_SOURCE.is_file():
        raise FirmwareError(f"Probe PlatformIO config not found: {PROBE_INI_SOURCE}")
    dest = firmware_root / PROBE_INI_NAME
    shutil.copy2(PROBE_INI_SOURCE, dest)
    return dest


def ensure_firmware(
    *,
    repo_url: str = DEFAULT_FIRMWARE_REPO,
    tag: str | None = None,
    on_line: LineSink = None,
) -> tuple[Path, str]:
    """Ensure ``.cache/firmware`` contains ``tag`` (latest release when omitted).

    Returns ``(firmware_root, checked_out_tag)``.
    """
    resolved_tag = tag or resolve_latest_tag(repo_url, on_line)
    if (
        _cached_tag() == resolved_tag
        and (FIRMWARE_DIR / "platformio.ini").is_file()
    ):
        _emit(on_line, f"Using cached firmware tag {resolved_tag}")
        install_probe_ini()
        return FIRMWARE_DIR, resolved_tag

    _emit(on_line, f"Fetching SlimeVR-Tracker-ESP tag {resolved_tag}...")
    _clone_firmware(repo_url, resolved_tag, on_line)
    _write_cached_tag(resolved_tag)
    install_probe_ini()
    return FIRMWARE_DIR, resolved_tag
