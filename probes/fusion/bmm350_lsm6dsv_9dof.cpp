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
#include "vqf.cpp"
#include "sensors/SensorFusion.cpp"
#include "sensors/softfusion/drivers/lsm6dsv.h"
#include "sensors/softfusion/magdriver.cpp"

namespace {

using SlimeVR::Logging::Logger;
using SlimeVR::Sensors::I2CImpl;
using SlimeVR::Sensors::SensorFusion;
using SlimeVR::Sensors::SoftFusion::Drivers::LSM6DSV;
using SlimeVR::Sensors::SoftFusion::MagDriver;
using SlimeVR::Sensors::SoftFusion::MagInterface;

Logger logger{"BMM3509DoF"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};
MagDriver magDriver;

class ProbeFusion : public SensorFusion {
public:
	using SensorFusion::SensorFusion;

	bool usesMag() const { return magExist; }
};

void printDivider() { Serial.println("----------------------------------------"); }

void setupHostI2C() {
	Wire.begin(static_cast<int>(PIN_IMU_SDA), static_cast<int>(PIN_IMU_SCL));
	Wire.setClock(I2C_SPEED);
	delay(50);
}

sensor_real_t vectorNorm(const sensor_real_t xyz[3]) {
	return std::sqrt(xyz[0] * xyz[0] + xyz[1] * xyz[1] + xyz[2] * xyz[2]);
}

bool isSaneMagSample(const sensor_real_t xyz[3]) {
	for (uint8_t i = 0; i < 3; i++) {
		if (!std::isfinite(static_cast<double>(xyz[i]))) {
			return false;
		}
	}

	const auto norm = vectorNorm(xyz);
	return norm >= 0.01f && norm <= 10.0f;
}

bool initMagDriver() {
	return magDriver.init(
		MagInterface{
			.readByte = [&](uint8_t address) { return imu.readAux(address); },
			.readBytes = [&](uint8_t address, uint8_t length, uint8_t* buffer) {
				return imu.readAuxBytes(address, length, buffer);
			},
			.writeByte = [&](uint8_t address, uint8_t value) {
				imu.writeAux(address, value);
			},
			.setDeviceId = [&](uint8_t deviceId) { imu.setAuxId(deviceId); },
			.startPolling =
				[&](uint8_t dataReg, SlimeVR::Sensors::SoftFusion::MagDataWidth dataWidth) {
					imu.startAuxPolling(dataReg, dataWidth);
				},
			.stopPolling = [&]() { imu.stopAuxPolling(); },
		},
		true
	);
}

bool readTrustedMagSample(sensor_real_t out[3]) {
	constexpr uint8_t kSampleLimit = 20;
	uint8_t saneReadCount = 0;

	magDriver.startPolling();
	for (uint8_t i = 0; i < kSampleLimit; i++) {
		float rawSample[3] = {0.0f, 0.0f, 0.0f};
		if (!magDriver.readSample(rawSample)) {
			Serial.printf("[FAIL] Sample %u read failed\n", i);
			magDriver.stopPolling();
			return false;
		}

		const sensor_real_t sample[3] = {
			static_cast<sensor_real_t>(rawSample[0]),
			static_cast<sensor_real_t>(rawSample[1]),
			static_cast<sensor_real_t>(rawSample[2]),
		};
		const bool sane = isSaneMagSample(sample);
		Serial.printf(
			"[MAG ] sample=%u x=%.6f y=%.6f z=%.6f |norm|=%.6f sane=%s\n",
			i,
			sample[0],
			sample[1],
			sample[2],
			vectorNorm(sample),
			sane ? "yes" : "no"
		);

		if (!sane) {
			saneReadCount = 0;
			delay(75);
			continue;
		}

		if (saneReadCount < 3) {
			saneReadCount++;
		}

		if (saneReadCount >= 3) {
			out[0] = sample[0];
			out[1] = sample[1];
			out[2] = sample[2];
			magDriver.stopPolling();
			return true;
		}

		delay(75);
	}

	magDriver.stopPolling();
	return false;
}

void runProbe() {
	Serial.println("BMM350 live 9DoF fusion path probe");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	printDivider();

	const auto whoAmI = imuRegisterInterface.readReg(LSM6DSV::Regs::WhoAmI::reg);
	if (whoAmI != LSM6DSV::Regs::WhoAmI::value) {
		Serial.printf(
			"[FAIL] LSM6DSV WHOAMI mismatch: expected 0x%02X got 0x%02X\n",
			LSM6DSV::Regs::WhoAmI::value,
			whoAmI
		);
		return;
	}
	Serial.println("[PASS] LSM6DSV WHOAMI matched");

	if (!imu.initialize()) {
		Serial.println("[FAIL] LSM6DSV initialization failed");
		return;
	}
	Serial.println("[PASS] LSM6DSV initialized");

	if (!initMagDriver()) {
		Serial.println("[FAIL] Failed to detect/init BMM350 through MagDriver");
		return;
	}

	const char* attachedMagName = magDriver.getAttachedMagName();
	Serial.printf(
		"[PASS] Detected mag: %s\n",
		attachedMagName != nullptr ? attachedMagName : "unknown"
	);

	sensor_real_t trustedMag[3] = {0.0f, 0.0f, 0.0f};
	if (!readTrustedMagSample(trustedMag)) {
		Serial.println("[FAIL] Failed to capture three consecutive sane MAG samples");
		return;
	}
	Serial.println("[PASS] Captured trusted live MAG sample");

	ProbeFusion fusion{
		LSM6DSV::SensorVQFParams,
		LSM6DSV::GyrTs,
		LSM6DSV::AccTs,
		LSM6DSV::MagTs,
	};

	const sensor_real_t accel[3] = {0.0f, 0.0f, 1.0f};
	const sensor_real_t gyro[3] = {0.0f, 0.0f, 0.0f};

	fusion.updateAcc(accel, LSM6DSV::AccTs);
	fusion.updateGyro(gyro, LSM6DSV::GyrTs);

	if (fusion.usesMag()) {
		Serial.println("[FAIL] Fusion unexpectedly started on the 9DoF path");
		return;
	}
	Serial.println("[PASS] Fusion starts on the 6DoF path");

	fusion.updateMag(trustedMag, LSM6DSV::MagTs);

	if (!fusion.usesMag()) {
		Serial.println("[FAIL] Fusion did not switch to the 9DoF path");
		return;
	}

	const auto* quaternion = fusion.getQuaternion();
	Serial.printf(
		"[PASS] Fusion switched to 9DoF path q=(%.6f, %.6f, %.6f, %.6f)\n",
		quaternion[0],
		quaternion[1],
		quaternion[2],
		quaternion[3]
	);
	printDivider();
	Serial.println("[PASS] 9DoF fusion path probe completed successfully");
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
