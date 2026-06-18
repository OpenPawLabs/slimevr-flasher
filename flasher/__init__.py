"""SlimeVR PCBA mass-flashing and verification tool.

Builds production and verification firmware once via PlatformIO, then watches
serial ports and concurrently flashes/verifies fresh boards (verify-then-ship).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
