import pytest

from flasher import flash


@pytest.mark.parametrize(
    "line,expected",
    [
        # esptool 4.x format: "(NN %)"
        ("Writing at 0x0000c000... (42 %)", 42),
        ("Writing at 0x00000000... (0 %)", 0),
        ("Writing at 0x0001f000... (100 %)", 100),
        ("Wrote 300000 bytes (123%)", 100),  # clamped
        # esptool 5.x format: "[bar]  NN.N%  bytes..."
        ("Writing at 0x00000000 [=>        ]   2.3%  4096/178432 bytes...", 2),
        ("Writing at 0x0000c000 [=====>    ]  42.7%  76000/178432 bytes...", 43),
        ("Writing at 0x0001f000 [==========] 100.0% 178432/178432 bytes...", 100),
        ("Hash of data verified.", None),
        ("Connecting....", None),
    ],
)
def test_parse_progress(line, expected):
    assert flash.parse_progress(line) == expected


def test_esptool_command_shape():
    cmd = flash.esptool_command("COM7", "fw.bin")
    assert cmd[1:3] == ["-m", "esptool"]
    assert cmd[cmd.index("--port") + 1] == "COM7"
    assert cmd[cmd.index("--chip") + 1] == "esp8266"
    assert "write_flash" in cmd
    assert cmd[-2:] == ["0x0", "fw.bin"]


def test_esptool_command_overrides():
    cmd = flash.esptool_command("COM1", "x.bin", baud=460800, flash_freq="80m")
    assert cmd[cmd.index("--baud") + 1] == "460800"
    assert cmd[cmd.index("--flash_freq") + 1] == "80m"
