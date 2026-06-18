import csv
import time
from pathlib import Path

from flasher.qa import QaCsvWriter, QaRecord, record_from_production_verify
from flasher.verify import ProductionVerifyResult, StepResult, Verdict


def test_qa_writer_appends_rows_sequentially(tmp_path):
    path = tmp_path / "qa-results.csv"
    writer = QaCsvWriter(path)
    writer.enqueue(
        QaRecord(
            mac_address="AA:BB:CC:DD:EE:FF",
            com_port="COM1",
            firmware_tag="v0.7.2",
            firmware_commit="abc123",
            board_type="BOARD_NODEMCU",
            overall_result="PASS",
            boot_check="PASS",
            get_info="PASS",
            wifi_scan="PASS",
            factory_reset="PASS",
            timestamp="2026-06-18T12:00:00+00:00",
        )
    )
    writer.close()

    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    assert rows[0]["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert rows[0]["overall_result"] == "PASS"


def test_qa_writer_writes_header_once(tmp_path):
    path = tmp_path / "qa-results.csv"
    writer = QaCsvWriter(path)
    for i in range(2):
        writer.enqueue(
            QaRecord(
                mac_address=f"AA:BB:CC:DD:EE:0{i}",
                com_port="COM1",
                firmware_tag="v0.7.2",
                firmware_commit="abc123",
                board_type="BOARD_NODEMCU",
                overall_result="PASS",
                boot_check="PASS",
                get_info="PASS",
                wifi_scan="PASS",
                factory_reset="PASS",
                timestamp=f"2026-06-18T12:00:0{i}+00:00",
            )
        )
    writer.close()

    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 2
    assert rows[0]["mac_address"] == "AA:BB:CC:DD:EE:00"
    assert rows[1]["mac_address"] == "AA:BB:CC:DD:EE:01"


def test_record_from_production_verify_failure():
    result = ProductionVerifyResult(
        verdict=Verdict.FAIL,
        mac_address="F0:24:F9:D2:8C:74",
        firmware_commit="c12c475",
        boot_check=StepResult.PASS,
        get_info=StepResult.PASS,
        wifi_scan=StepResult.FAIL,
        factory_reset=StepResult.SKIP,
        failure_reason="GET WIFISCAN: found 0 networks, need at least 1",
    )
    record = record_from_production_verify(
        port="COM4",
        board_type="BOARD_NODEMCU",
        firmware_tag="v0.7.2",
        result=result,
    )
    assert record.overall_result == "FAIL"
    assert record.wifi_scan == "FAIL"
    assert record.factory_reset == "SKIP"
    assert "0 networks" in record.failure_reason


def test_qa_writer_queue_serializes_concurrent_enqueues(tmp_path):
    path = tmp_path / "qa-results.csv"
    writer = QaCsvWriter(path)
    for i in range(20):
        writer.enqueue(
            QaRecord(
                mac_address=f"AA:BB:CC:DD:EE:{i:02X}",
                com_port="COM1",
                firmware_tag="v0.7.2",
                firmware_commit="abc123",
                board_type="BOARD_NODEMCU",
                overall_result="PASS",
                boot_check="PASS",
                get_info="PASS",
                wifi_scan="PASS",
                factory_reset="PASS",
            )
        )
    time.sleep(0.2)
    writer.close()
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 20
