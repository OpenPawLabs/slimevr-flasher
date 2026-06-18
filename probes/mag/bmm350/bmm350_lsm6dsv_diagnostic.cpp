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

constexpr uint8_t kBmm350Address = 0x14;
constexpr uint8_t kBmm350DataRegister = 0x31;

constexpr float kBmm350Power = 1000000.0f / 1048576.0f;
constexpr float kBmm350BxySens = 14.55f;
constexpr float kBmm350BzSens = 9.0f;
constexpr float kBmm350InaXyGainTarget = 19.46f;
constexpr float kBmm350InaZGainTarget = 31.0f;
constexpr float kBmm350AdcGain = 1.0f / 1.5f;
constexpr float kBmm350LutGain = 0.714607238769531f;
constexpr float kBmm350SensitivityXY
	= kBmm350Power
	/ (kBmm350BxySens * kBmm350InaXyGainTarget * kBmm350AdcGain * kBmm350LutGain);
constexpr float kBmm350SensitivityZ
	= kBmm350Power
	/ (kBmm350BzSens * kBmm350InaZGainTarget * kBmm350AdcGain * kBmm350LutGain);

Logger logger{"BMM350Diag"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};
MagDriver magDriver;

void setupHostI2C() {
	Wire.begin(static_cast<int>(PIN_IMU_SDA), static_cast<int>(PIN_IMU_SCL));
	Wire.setClock(I2C_SPEED);
	delay(50);
}

int32_t unpackBmm35021Bit(const uint8_t* rawAxis) {
	return static_cast<int32_t>(
			   (static_cast<int32_t>(rawAxis[2]) << 24)
			   | (static_cast<int32_t>(rawAxis[1]) << 16)
			   | (static_cast<int32_t>(rawAxis[0]) << 8)
		   )
		/ 256;
}

void parseCandidate(const uint8_t* raw, uint8_t offset, float out[3]) {
	for (uint8_t i = 0; i < 3; i++) {
		const auto unpacked = unpackBmm35021Bit(&raw[offset + (3 * i)]);
		const auto sensitivity = i < 2 ? kBmm350SensitivityXY : kBmm350SensitivityZ;
		out[i] = (static_cast<float>(unpacked) * sensitivity) / 100.0f;
	}
}

float vectorNorm(const float v[3]) {
	return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

bool isSaneMagSample(const float v[3]) {
	for (uint8_t i = 0; i < 3; i++) {
		if (!std::isfinite(v[i])) {
			return false;
		}
	}

	const auto norm = vectorNorm(v);
	return norm >= 0.01f && norm <= 10.0f;
}

void printRaw(const uint8_t* raw, uint8_t len) {
	Serial.print("[RAW] ");
	for (uint8_t i = 0; i < len; i++) {
		Serial.printf("%02X", raw[i]);
		if (i + 1 < len) {
			Serial.print(" ");
		}
	}
	Serial.println();
}

bool initializeMagPath() {
	const auto whoAmI = imuRegisterInterface.readReg(LSM6DSV::Regs::WhoAmI::reg);
	if (whoAmI != LSM6DSV::Regs::WhoAmI::value) {
		Serial.printf(
			"[FAIL] LSM6DSV WHOAMI mismatch: expected 0x%02X got 0x%02X\n",
			LSM6DSV::Regs::WhoAmI::value,
			whoAmI
		);
		return false;
	}

	if (!imu.initialize()) {
		Serial.println("[FAIL] LSM6DSV initialization failed");
		return false;
	}

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
			.startPolling =
				[&](uint8_t dataReg, SlimeVR::Sensors::SoftFusion::MagDataWidth dataWidth
				) { imu.startAuxPolling(dataReg, dataWidth); },
			.stopPolling = [&]() { imu.stopAuxPolling(); },
		},
		true
	);
	if (!magInit) {
		Serial.println("[FAIL] Failed to detect/init BMM350");
		return false;
	}

	Serial.printf(
		"[PASS] Detected mag: %s\n",
		magDriver.getAttachedMagName() ? magDriver.getAttachedMagName() : "unknown"
	);
	magDriver.startPolling();
	return true;
}

void runProbe() {
	Serial.println("BMM350 diagnostic test via LSM6DSV passthrough");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	Serial.println("----------------------------------------");

	if (!initializeMagPath()) {
		return;
	}

	imu.setAuxId(kBmm350Address);
	constexpr uint8_t kRawLength = 12;
	constexpr uint8_t kSamples = 12;

	for (uint8_t sampleIndex = 0; sampleIndex < kSamples; sampleIndex++) {
		uint8_t raw[kRawLength] = {0};
		if (!imu.readAuxBytes(kBmm350DataRegister, kRawLength, raw)) {
			Serial.printf("[FAIL] raw read failed for sample %u\n", sampleIndex);
			magDriver.stopPolling();
			return;
		}

		printRaw(raw, kRawLength);

		float driverSample[3] = {0.0f, 0.0f, 0.0f};
		const bool driverReadOk = magDriver.readSample(driverSample);
		if (driverReadOk) {
			Serial.printf(
				"[DRV ] idx=%u x=%.6f y=%.6f z=%.6f |norm|=%.6f sane=%s\n",
				sampleIndex,
				driverSample[0],
				driverSample[1],
				driverSample[2],
				vectorNorm(driverSample),
				isSaneMagSample(driverSample) ? "yes" : "no"
			);
		} else {
			Serial.printf("[DRV ] idx=%u read failed\n", sampleIndex);
		}

		for (uint8_t offset = 0; offset <= 3; offset++) {
			float parsed[3] = {0.0f, 0.0f, 0.0f};
			parseCandidate(raw, offset, parsed);
			Serial.printf(
				"[OFF%u] idx=%u x=%.6f y=%.6f z=%.6f |norm|=%.6f\n",
				offset,
				sampleIndex,
				parsed[0],
				parsed[1],
				parsed[2],
				vectorNorm(parsed)
			);
		}

		Serial.println("----------------------------------------");
		delay(100);
	}

	magDriver.stopPolling();
	Serial.println("[PASS] Diagnostic capture completed");
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
