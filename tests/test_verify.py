from flasher.verify import (
    Verdict,
    all_fragments_seen,
    evaluate,
    parse_git_commit,
    parse_mac,
    parse_sensor0,
    parse_wifi_network_count,
    validate_get_info,
    validate_wifi_scan,
)

INFO_LINES = [
    "[INFO ] [SerialCommands] SlimeVR Tracker, board: 3, hardware: 1, protocol: 21, firmware: 0.7.2, address: (IP unset), mac: F0:24:F9:D2:8C:74, status: 0, wifi state: 4",
    "[INFO ] [SerialCommands] Vendor: OpenPaw Labs (https://openpawlabs.com), product: OpenPaw Tracker, firmware update url: , name: ",
    "[INFO ] [SerialCommands] Sensor[0]: LSM6DSV (0.016 -0.696 0.001 0.718) is working: true, had data: true",
    "[INFO ] [SerialCommands] Battery voltage: 4.946, level: 100.0%",
    "[INFO ] [SerialCommands] Git commit: c12c475",
]

WSCAN_LINES = [
    "[INFO ] [SerialCommands] [WSCAN] Scanning for WiFi networks...",
    "[INFO ] [SerialCommands] [WSCAN] Found 12 networks:",
    "[INFO ] [SerialCommands] [WSCAN] 0:\t23\t'WIFI NETWORK NAME'\t(-53 dBm)\tWPA2_PSK",
]

BOOT_FRAGMENTS = [
    "[INFO ] [SlimeVR] SlimeVR",
    "[INFO ] [SensorManager] Sensor 0 configured",
]


# -- probe verification -------------------------------------------------


def test_pass_marker_before_end():
    assert evaluate(["LSM6DSV smoke test", "[VERIFY_PASS]", "[TEST_END]"]) is Verdict.PASS


def test_end_without_pass_is_fail():
    assert evaluate(["some output", "[TEST_END]"]) is Verdict.FAIL


def test_no_end_marker_is_timeout():
    assert evaluate(["partial output", "[VERIFY_PASS]"]) is Verdict.TIMEOUT


# -- production parsers -------------------------------------------------


def test_parse_mac():
    assert parse_mac(INFO_LINES) == "F0:24:F9:D2:8C:74"


def test_parse_sensor0():
    assert parse_sensor0(INFO_LINES) == ("LSM6DSV", True, True)


def test_parse_git_commit():
    assert parse_git_commit(INFO_LINES) == "c12c475"


def test_validate_get_info_pass():
    ok, mac, commit, reason = validate_get_info(INFO_LINES, expected_imu="LSM6DSV")
    assert ok is True
    assert mac == "F0:24:F9:D2:8C:74"
    assert commit == "c12c475"
    assert reason == ""


def test_validate_get_info_wrong_imu():
    ok, _, _, reason = validate_get_info(INFO_LINES, expected_imu="ICM20948")
    assert ok is False
    assert "expected ICM20948" in reason


def test_validate_get_info_not_working():
    lines = [
        "[INFO ] [SerialCommands] mac: AA:BB:CC:DD:EE:FF, status: 0",
        "[INFO ] [SerialCommands] Sensor[0]: LSM6DSV (0 0 0 0) is working: false, had data: true",
    ]
    ok, _, _, reason = validate_get_info(lines, expected_imu="LSM6DSV")
    assert ok is False
    assert "not working" in reason


def test_parse_wifi_network_count():
    assert parse_wifi_network_count(WSCAN_LINES) == 12


def test_parse_wifi_scan_failed():
    assert parse_wifi_network_count(["[WSCAN] Scan failed!"]) == -1


def test_validate_wifi_scan_pass():
    ok, reason = validate_wifi_scan(WSCAN_LINES, min_networks=1)
    assert ok is True
    assert reason == ""


def test_validate_wifi_scan_insufficient():
    lines = ["[WSCAN] Found 0 networks:"]
    ok, reason = validate_wifi_scan(lines, min_networks=1)
    assert ok is False
    assert "found 0 networks" in reason


def test_all_fragments_seen_across_lines():
    lines = [
        "booting...",
        "[INFO ] [SlimeVR] SlimeVR Server v1.2 starting",
        "[INFO ] [SensorManager] Sensor 0 configured: LSM6DSV",
    ]
    assert all_fragments_seen(lines, BOOT_FRAGMENTS) is True


def test_missing_fragment_is_not_seen():
    lines = ["[INFO ] [SlimeVR] SlimeVR Server v1.2 starting", "no sensor here"]
    assert all_fragments_seen(lines, BOOT_FRAGMENTS) is False
