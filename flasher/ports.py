"""Serial port detection and connect/disconnect tracking.

The diff logic is pure (and unit-tested); only the live enumeration touches
pyserial, which is imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def list_serial_ports() -> set[str]:
    """Return the set of currently present serial port device names."""
    from serial.tools import list_ports  # lazy import

    return {port.device for port in list_ports.comports()}


def diff_ports(known: set[str], current: set[str]) -> tuple[set[str], set[str]]:
    """Return ``(added, removed)`` between a known and a current port set."""
    return current - known, known - current


@dataclass
class PortMonitor:
    """Tracks present ports across polls and reports deltas.

    Feed it the current port set via :meth:`poll`; it returns the
    ``(added, removed)`` deltas and updates its internal known set.
    """

    known: set[str] = field(default_factory=set)

    def poll(self, current: set[str]) -> tuple[set[str], set[str]]:
        added, removed = diff_ports(self.known, current)
        self.known = set(current)
        return added, removed
