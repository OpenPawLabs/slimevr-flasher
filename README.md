# slimevr-flasher

Bulk flashing tool for DIY SlimeVR PCBA boards. It builds production firmware from a
tagged [SlimeVR-Tracker-ESP](https://github.com/SlimeVR/SlimeVR-Tracker-ESP) release,
runs hardware verification probes from this repository, then flashes the shippable
production image when every check passes.

## How it works

```
fetch tagged firmware (git)        build once (PlatformIO)         per armed port (parallel)
+---------------------------+      +-------------------+           +----------------------------------+
| SlimeVR-Tracker-ESP @ tag | ---> | production.bin    |  board -> | FLASH probe -> VERIFY -> ...     |
| cached under .cache/      |      | test_<probe>.bin  |           | FLASH prod -> VERIFY boot -> PASS|
+---------------------------+      +-------------------+           +----------------------------------+
```

On startup the tool:

1. Resolves the latest upstream release tag (or uses `--firmware-tag`).
2. Shallow-clones that tag into `.cache/firmware/` (reused on later runs).
3. Builds production firmware from the clone and each probe from `probes/`.
4. Watches serial ports and runs the verify-then-ship pipeline on every armed port.

Because firmware is built once and cached, per-board flashing is pure `esptool` and
safe to run in parallel across ports.

> **Scope:** v1 targets `BOARD_NODEMCU` (ESP8266) dev boards with DTR/RTS auto-reset.
> ESP32-family boards (multi-image flashing) are future work.

## Repository layout

```
slimevr-flasher/
├── config/           # board profiles (board-config.json, schemas)
├── flasher/          # Python TUI, PlatformIO probe config, requirements
├── probes/           # hardware verification smoke tests
├── tests/            # Python unit tests
├── launch.bat        # Windows quick-start
└── launch.sh         # macOS / Linux quick-start
```

## Setup

Requires Python 3, Git, and PlatformIO (`pio`) on `PATH`.

```bash
pip install -r flasher/requirements.txt
```

Or use the launch scripts (install requirements automatically, then start the TUI):

- **Windows:** double-click `launch.bat`, or run `launch.bat` from a terminal
- **macOS / Linux:** `./launch.sh` (run `chmod +x launch.sh` once if needed)

Both scripts accept the same arguments as `python -m flasher`, for example
`launch.bat --firmware-tag v0.7.2`.

## Usage

Run from the repository root:

```bash
python -m flasher
python -m flasher --config config/board-config.json
python -m flasher --firmware-tag v0.7.2
```

### Key bindings

| Key | Action |
|-----|--------|
| `a` | Arm all detected ports |
| `d` | Disarm idle slots |
| `l` | Toggle build/log panel |
| `q` | Quit |

Workflow:

1. On launch the tool fetches firmware (first run) and builds images (log expands during build).
2. Arm the ports you are flashing on.
3. Plug a board — the armed port runs verification probes, then production firmware.
4. After PASS/FAIL, unplug and plug the next board; armed ports auto-flash again.

Production verification runs automatically when `productionVerify` is configured:
boot confirmation, `GET INFO` (MAC + IMU), `GET WIFISCAN`, factory reset, and reboot check.
Results append to `qa-results.csv` at the repository root.

## Configuration (`config/`)

Board profiles live in [`config/`](config/). The default is
[`config/board-config.json`](config/board-config.json), validated against
`board-config.schema.json` (which reuses SlimeVR's `board-defaults.schema.json`
for board `values`).

| Field | Purpose |
|-------|---------|
| `type` | PlatformIO environment / board to build (e.g. `BOARD_NODEMCU`) |
| `tests` | Probe source paths under `probes/`, flashed in order |
| `productionVerify.bootFragments` | Boot log fragments required before and after factory reset |
| `productionVerify.postBootDelaySeconds` | Delay after boot before sending commands (default 3) |
| `productionVerify.expectedSensor0Imu` | IMU name Sensor[0] must report (e.g. `LSM6DSV`) |
| `productionVerify.minWifiNetworks` | Minimum networks `GET WIFISCAN` must find (default 1) |
| `defaults.<type>.values` | Board values injected at build time via `SLIMEVR_OVERRIDE_DEFAULTS` |
| `defaults.<type>.flashingRules` | Standard SlimeVR flashing rules |

## Verification probes (`probes/`)

Hardware smoke tests live under `probes/` and compile against the cached firmware tree.
Each probe used for automated verification must emit a machine-readable verdict via
`probe_result.h`:

```cpp
finishProbe(runProbe());  // prints [VERIFY_PASS]/[VERIFY_FAIL] then [TEST_END]
```

Run a single probe manually:

```bash
python probes/run_test.py --port COM4 --test-src imu/lsm6dsv/lsm6dsv_smoke_test.cpp
```

See [probes/README.md](probes/README.md) for the full probe catalog.

## Development

```bash
python -m pytest tests
```

Unit tests cover config validation, firmware checkout logic, slot state machine, and
headless TUI startup (with mocked builds — no hardware or network required).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
