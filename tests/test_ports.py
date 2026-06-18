from flasher.ports import PortMonitor, diff_ports


def test_diff_added_and_removed():
    added, removed = diff_ports({"COM1", "COM2"}, {"COM2", "COM3"})
    assert added == {"COM3"}
    assert removed == {"COM1"}


def test_monitor_tracks_sequence():
    monitor = PortMonitor()

    added, removed = monitor.poll({"COM1"})
    assert added == {"COM1"} and removed == set()

    added, removed = monitor.poll({"COM1", "COM3"})
    assert added == {"COM3"} and removed == set()

    added, removed = monitor.poll({"COM3"})
    assert added == set() and removed == {"COM1"}

    added, removed = monitor.poll({"COM3"})
    assert added == set() and removed == set()
