from flasher import builder


def test_src_filter_strips_probes_prefix():
    assert (
        builder._src_filter_for("probes/imu/lsm6dsv/lsm6dsv_smoke_test.cpp")
        == "+<imu/lsm6dsv/lsm6dsv_smoke_test.cpp>"
    )


def test_src_filter_without_prefix_is_passthrough():
    assert builder._src_filter_for("mag/foo.cpp") == "+<mag/foo.cpp>"


def test_cache_name_derives_from_stem():
    assert (
        builder._cache_name_for("probes/imu/lsm6dsv/lsm6dsv_smoke_test.cpp")
        == "test_lsm6dsv_smoke_test.bin"
    )


def test_production_env_includes_openpaw_branding():
    from flasher.config import load_board_config

    config = load_board_config()
    env = builder._production_env_overrides(config)
    assert "OpenPaw Labs" in env["PLATFORMIO_BUILD_FLAGS"]
    assert "https://openpawlabs.com" in env["PLATFORMIO_BUILD_FLAGS"]
    assert "OpenPaw Tracker" in env["PLATFORMIO_BUILD_FLAGS"]
