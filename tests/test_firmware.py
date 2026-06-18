"""Tests for firmware repository checkout."""

from __future__ import annotations

import pytest

from flasher import firmware as fw


def test_resolve_latest_tag_picks_newest(monkeypatch):
    def fake_run(args, on_line=None):
        assert args[:3] == ["ls-remote", "--tags", "--sort=-v:refname"]
        return (
            "abc123\trefs/tags/v0.9.0\n"
            "def456\trefs/tags/v0.9.0^{}\n"
            "ghi789\trefs/tags/v0.8.0\n"
        )

    monkeypatch.setattr(fw, "_run_git", fake_run)
    assert fw.resolve_latest_tag("https://example.com/repo.git") == "v0.9.0"


def test_resolve_latest_tag_skips_annotated_suffix_only(monkeypatch):
    def fake_run(args, on_line=None):
        return "abc123\trefs/tags/v1.0.0^{}\n"

    monkeypatch.setattr(fw, "_run_git", fake_run)
    with pytest.raises(fw.FirmwareError, match="No release tags"):
        fw.resolve_latest_tag("https://example.com/repo.git")


def test_ensure_firmware_uses_cache_when_tag_matches(tmp_path, monkeypatch):
    root = tmp_path / "flasher"
    cache = root / ".cache"
    firmware = cache / "firmware"
    firmware.mkdir(parents=True)
    (firmware / "platformio.ini").write_text("[platformio]\n", encoding="utf-8")
    (cache / "firmware_tag.txt").write_text("v1.2.3\n", encoding="utf-8")

    monkeypatch.setattr(fw, "FLASHER_ROOT", root)
    monkeypatch.setattr(fw, "CACHE_DIR", cache)
    monkeypatch.setattr(fw, "FIRMWARE_DIR", firmware)
    monkeypatch.setattr(fw, "TAG_STAMP", cache / "firmware_tag.txt")

    def fail_clone(*args, **kwargs):
        raise AssertionError("clone should not run when cache matches")

    monkeypatch.setattr(fw, "_clone_firmware", fail_clone)

    path, tag = fw.ensure_firmware(tag="v1.2.3")
    assert path == firmware
    assert tag == "v1.2.3"
