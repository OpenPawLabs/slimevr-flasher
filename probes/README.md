# Hardware verification probes

Use a probe when a functionality needs to be checked against a real device — for
example confirming an IMU responds on I2C before shipping a board.

Keep each probe small, focused, and easy to run.

Suggested layout:

- `imu/`
- `mag/`
- `fusion/`

The current probes target DIY NodeMCU-based SlimeVR dev boards, but could be
expanded for other board profiles later.

Current probes:

- `imu/lsm6dsv/lsm6dsv_smoke_test.cpp`
- `mag/bmm350/bmm350_lsm6dsv_bringup.cpp`
- `mag/bmm350/bmm350_lsm6dsv_alignment_probe.cpp`
- `fusion/bmm350_lsm6dsv_9dof.cpp`

## Verification verdict markers

Probes used for automated verification (by `python -m flasher`) must end with a
single machine-readable verdict. Use the shared helper in `probe_result.h`:

```cpp
#include "probe_result.h"

bool runProbe() { /* ... */ return ok; }

void setup() {
	// ...
	finishProbe(runProbe());  // prints [VERIFY_PASS] or [VERIFY_FAIL], then [TEST_END]
}
```

A probe counts as PASS only when `[VERIFY_PASS]` is printed before `[TEST_END]`.
The per-step `[PASS]`/`[FAIL]` lines remain useful for operators reading the log.

## Running a probe manually

The helper fetches the latest tagged SlimeVR-Tracker-ESP release on first run,
then uploads and monitors the probe:

```bash
python probes/run_test.py --port COM4 --test-src imu/lsm6dsv/lsm6dsv_smoke_test.cpp
python probes/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_bringup.cpp
python probes/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_alignment_probe.cpp --monitor-timeout-seconds 90
python probes/run_test.py --port COM4 --test-src fusion/bmm350_lsm6dsv_9dof.cpp --monitor-timeout-seconds 20
```

Direct PlatformIO example (from the cached firmware checkout, after `ensure_firmware`):

```bash
cd .cache/firmware
PLATFORMIO_BUILD_SRC_FILTER='+<imu/lsm6dsv/lsm6dsv_smoke_test.cpp>' pio run -c platformio.nodemcu.probe.ini -e integration_nodemcu_probe -t upload --upload-port COM4
pio device monitor -p COM4 -b 115200 --filter direct
```
