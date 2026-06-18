import json

import pytest

from flasher import config as cfg


def real_raw() -> dict:
    return json.loads(cfg.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def test_real_config_loads():
    bc = cfg.load_board_config()
    assert bc.board_type == "BOARD_NODEMCU"
    assert bc.tests
    assert "SENSORS" in bc.values
    assert "applicationOffset" in bc.flashing_rules
    assert bc.branding["VENDOR_NAME"] == "OpenPaw Labs"
    assert bc.firmware_filename == "BOARD_SLIMEVR_OPENPAW_BLUEBERRY-firmware.bin"


def test_production_verify_loaded():
    bc = cfg.load_board_config()
    assert bc.production_verify is not None
    assert bc.production_verify.expected_sensor0_imu == "LSM6DSV"
    assert any("SlimeVR" in frag for frag in bc.production_verify.boot_fragments)


def test_production_verify_default_none(tmp_path):
    raw = real_raw()
    raw.pop("productionVerify", None)
    path = tmp_path / "board-config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert cfg.load_board_config(path).production_verify is None


def test_validate_good_config_passes():
    cfg.validate_config(real_raw())


def test_missing_type_fails_schema():
    raw = real_raw()
    del raw["type"]
    with pytest.raises(cfg.ConfigError):
        cfg.validate_config(raw)


def test_unknown_board_type_fails_schema():
    raw = real_raw()
    raw["type"] = "BOARD_NOT_REAL"
    with pytest.raises(cfg.ConfigError):
        cfg.validate_config(raw)


def test_type_without_defaults_entry(tmp_path):
    raw = real_raw()
    # Valid enum value, but no matching entry under "defaults".
    raw["type"] = "BOARD_WEMOSD1MINI"
    path = tmp_path / "board-config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="no matching entry"):
        cfg.load_board_config(path)


def test_missing_test_source_fails(tmp_path):
    raw = real_raw()
    raw["tests"] = ["probes/does/not/exist.cpp"]
    path = tmp_path / "board-config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(cfg.ConfigError, match="not found"):
        cfg.load_board_config(path)
