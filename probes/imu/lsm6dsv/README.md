# LSM6DSV Tests

Verifies basic `LSM6DSV` bring-up on real hardware.

This is intended for custom NodeMCU-based DIY SlimeVR development boards that use `LSM6DSV` on the primary host I2C bus. It is not intended for vanilla SlimeVR tracker builds.

What it checks:

- the host can reach the `LSM6DSV`
- `LSM6DSV` WHOAMI matches
- the `LSM6DSV` driver initializes successfully

What it does not check:

- downstream magnetometer passthrough behavior (see mag/bmm350 folder)
- fusion behavior
- FIFO stress/soak behavior

## Current tests

- `lsm6dsv_smoke_test.cpp`

## Running
```bash
python test/integration/run_test.py --port COM4 --test-src imu/lsm6dsv/lsm6dsv_smoke_test.cpp
```