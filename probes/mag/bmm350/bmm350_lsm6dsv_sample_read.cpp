#include <Arduino.h>
#include <Wire.h>
#include <i2cscan.h>

#include <cmath>

#include "globals.h"
#include "logging/Level.cpp"
#include "logging/Logger.h"
#include "logging/Logger.cpp"
#include "I2Cdev.cpp"
#include "sensorinterface/i2cimpl.h"
#include "sensors/softfusion/drivers/lsm6dsv.h"
#include "sensors/softfusion/magdriver.cpp"

namespace {

using SlimeVR::Logging::Logger;
using SlimeVR::Sensors::I2CImpl;
using SlimeVR::Sensors::SoftFusion::Drivers::LSM6DSV;
using SlimeVR::Sensors::SoftFusion::MagDriver;
using SlimeVR::Sensors::SoftFusion::MagInterface;

Logger logger{"BMM350Read"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};
MagDriver magDriver;

void setupHostI2C() {
	Wire.begin(static_cast<int>(PIN_IMU_SDA), static_cast<int>(PIN_IMU_SCL));
	Wire.setClock(I2C_SPEED);
	delay(50);
}

uint8_t readImuWhoAmI() {
	return imuRegisterInterface.readReg(LSM6DSV::Regs::WhoAmI::reg);
}

void printImuBusDiagnostics() {
	const bool devicePresent = I2CSCAN::hasDevOnBus(LSM6DSV::Address);
	Serial.printf(
		"[INFO] I2C device at 0x%02X: %s\n",
		LSM6DSV::Address,
		devicePresent ? "present" : "not found"
	);

	const int clearResult = I2CSCAN::clearBus(PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("[INFO] I2C clearBus result: %d\n", clearResult);

	setupHostI2C();
	delay(20);

	Serial.printf("[INFO] WHOAMI after clearBus: 0x%02X\n", readImuWhoAmI());
}

bool hasSampleChanged(const float sample[3], const float previous[3]) {
	constexpr float kChangeThreshold = 1e-4f;
	return std::fabs(sample[0] - previous[0]) > kChangeThreshold
		|| std::fabs(sample[1] - previous[1]) > kChangeThreshold
		|| std::fabs(sample[2] - previous[2]) > kChangeThreshold;
}

void runProbe() {
	Serial.println("BMM350 sample read test via LSM6DSV passthrough");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	Serial.println("----------------------------------------");

	const auto whoAmI = readImuWhoAmI();
	if (whoAmI != LSM6DSV::Regs::WhoAmI::value) {
		Serial.printf(
			"[FAIL] LSM6DSV WHOAMI mismatch: expected 0x%02X got 0x%02X\n",
			LSM6DSV::Regs::WhoAmI::value,
			whoAmI
		);
		printImuBusDiagnostics();
		return;
	}
	Serial.println("[PASS] LSM6DSV WHOAMI matched");

	if (!imu.initialize()) {
		Serial.println("[FAIL] LSM6DSV initialization failed");
		return;
	}
	Serial.println("[PASS] LSM6DSV initialized");

	const bool magInit = magDriver.init(
		MagInterface{
			.readByte = [&](uint8_t address) { return imu.readAux(address); },
			.readBytes = [&](uint8_t address, uint8_t length, uint8_t* buffer) {
				return imu.readAuxBytes(address, length, buffer);
			},
			.writeByte = [&](uint8_t address, uint8_t value) {
				imu.writeAux(address, value);
			},
			.setDeviceId = [&](uint8_t deviceId) { imu.setAuxId(deviceId); },
			.startPolling = [&](uint8_t dataReg, SlimeVR::Sensors::SoftFusion::MagDataWidth dataWidth) {
				imu.startAuxPolling(dataReg, dataWidth);
			},
			.stopPolling = [&]() { imu.stopAuxPolling(); },
		},
		true
	);

	if (!magInit) {
		Serial.println("[FAIL] Failed to detect/init BMM350 through MagDriver");
		return;
	}

	const char* attachedMagName = magDriver.getAttachedMagName();
	Serial.printf(
		"[PASS] Detected mag: %s\n",
		attachedMagName != nullptr ? attachedMagName : "unknown"
	);

	magDriver.startPolling();

	bool sawNonZero = false;
	bool sawAnyChange = false;
	float previousSample[3] = {0.0f, 0.0f, 0.0f};

	constexpr uint8_t kSampleCount = 100;
	for (uint8_t i = 0; i < kSampleCount; i++) {
		float sample[3] = {0.0f, 0.0f, 0.0f};
		if (!magDriver.readSample(sample)) {
			Serial.printf("[FAIL] Sample %u read failed\n", i);
			magDriver.stopPolling();
			return;
		}

		const float magnitude
			= std::fabs(sample[0]) + std::fabs(sample[1]) + std::fabs(sample[2]);
		if (magnitude > 1e-6f) {
			sawNonZero = true;
		}
		if (i > 0 && hasSampleChanged(sample, previousSample)) {
			sawAnyChange = true;
		}

		previousSample[0] = sample[0];
		previousSample[1] = sample[1];
		previousSample[2] = sample[2];

		Serial.printf(
			"[DATA] sample=%u x=%.6f y=%.6f z=%.6f gauss\n",
			i,
			sample[0],
			sample[1],
			sample[2]
		);
		delay(75);
	}

	magDriver.stopPolling();

	if (!sawNonZero) {
		Serial.println("[FAIL] All samples were zero");
		return;
	}

	if (!sawAnyChange) {
		Serial.println(
			"[WARN] Samples did not change; rotate the board to confirm orientation response"
		);
	}

	Serial.println("[PASS] BMM350 sample reads succeeded");
	Serial.println("----------------------------------------");
	Serial.println("[PASS] BMM350 sample read test completed successfully");
}

}  // namespace

void setup() {
	Serial.begin(115200);
	delay(2000);
	Serial.println();
	setupHostI2C();
	runProbe();
	Serial.println("[TEST_END]");
}

void loop() { delay(1000); }
