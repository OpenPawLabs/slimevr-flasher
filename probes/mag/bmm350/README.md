# BMM350 Tests

Verifies that a `BMM350` mag can be detected through `LSM6DSV` sensor-hub passthrough on DIY NodeMCU-based DIY SlimeVR dev boards.

What it checks:

- the host can reach and initialize the `LSM6DSV`
- `BMM350` CHIP_ID can be read through passthrough using the required dummy-byte discard
- `MagDriver` can detect/init `BMM350` and read repeated XYZ samples through passthrough

What it does not check:

- fusion behavior
- 9DoF fusion hookup

## Current tests

- `bmm350_lsm6dsv_bringup.cpp`
- `bmm350_lsm6dsv_sample_read.cpp`
- `bmm350_lsm6dsv_diagnostic.cpp`
- `bmm350_lsm6dsv_alignment_probe.cpp`

## Implementation note

- magnetometer definitions now live under `src/sensors/softfusion/drivers/mag/`
- `BMM350`-specific setup/probe/read/parse logic lives in `src/sensors/softfusion/drivers/mag/bmm350.h`
- `src/sensors/softfusion/magdriver.cpp` keeps generic detection/read orchestration
- the current `BMM350` driver remaps samples into the `LSM6DSV`/body frame for the
  current DIY board assumption: `LSM6DSV = ROT_0`, `BMM350 = ROT_270`

## Hardware assumptions

Default constants in `bmm350_lsm6dsv_bringup.cpp` assume:

- `LSM6DSV` on the primary host I2C bus
- `BMM350` on the `LSM6DSV` auxiliary bus
- downstream address `0x14`
- CHIP_ID register `0x00`
- expected CHIP_ID value `0x33`

## Run tests

```bash
python test/integration/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_bringup.cpp
```

```bash
python test/integration/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_sample_read.cpp
```

```bash
python test/integration/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_diagnostic.cpp --monitor-timeout-seconds 20
```

```bash
python test/integration/run_test.py --port COM4 --test-src mag/bmm350/bmm350_lsm6dsv_alignment_probe.cpp --monitor-timeout-seconds 90
```
