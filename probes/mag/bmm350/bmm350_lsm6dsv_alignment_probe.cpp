#include <Arduino.h>
#include <Wire.h>
#include <i2cscan.h>

#include <cmath>
#include <cstdint>

#include "globals.h"
#include "logging/Level.cpp"
#include "logging/Logger.cpp"
#include "logging/Logger.h"
#include "I2Cdev.cpp"
#include "sensorinterface/i2cimpl.h"
#include "sensors/softfusion/drivers/lsm6dsv.h"
#include "sensors/softfusion/imuconsts.h"
#include "sensors/softfusion/magdriver.cpp"

namespace {

using SlimeVR::Logging::Logger;
using SlimeVR::Sensors::I2CImpl;
using SlimeVR::Sensors::SoftFusion::Drivers::LSM6DSV;
using SlimeVR::Sensors::SoftFusion::MagDriver;
using SlimeVR::Sensors::SoftFusion::MagInterface;

constexpr uint8_t kBmm350Address = 0x14;
constexpr uint8_t kBmm350BurstLength = 11;
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

constexpr uint16_t kMoveDelayMs = 10000;
constexpr uint16_t kSampleIntervalMs = 1000;
constexpr uint8_t kStageSamples = 5;

Logger logger{"BMM350Align"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};
MagDriver magDriver;

struct Stage {
	const char* name;
	const char* instruction;
};

constexpr Stage kStages[] = {
	{
		"vertical_default",
		"Hold the board in the default vertical orientation and keep it still.",
	},
	{
		"flat_horizontal",
		"Lay the PCB flat/horizontal and keep it still.",
	},
	{
		"left_side",
		"Stand the board on its left side and keep it still.",
	},
	{
		"right_side",
		"Stand the board on its right side and keep it still.",
	},
	{
		"vertical_yaw_cw",
		"Return to default vertical, then slowly rotate about yaw 90 degrees clockwise and hold.",
	},
};

void printDivider() { Serial.println("----------------------------------------"); }

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

int32_t unpackBmm35021Bit(const uint8_t* rawAxis) {
	return static_cast<int32_t>(
			   (static_cast<int32_t>(rawAxis[2]) << 24)
			   | (static_cast<int32_t>(rawAxis[1]) << 16)
			   | (static_cast<int32_t>(rawAxis[0]) << 8)
		   )
		/ 256;
}

void parseRawBmm350(const uint8_t* raw, float out[3]) {
	for (uint8_t i = 0; i < 3; i++) {
		const auto unpacked = unpackBmm35021Bit(&raw[i * 3]);
		const auto sensitivity = i < 2 ? kBmm350SensitivityXY : kBmm350SensitivityZ;
		out[i] = (static_cast<float>(unpacked) * sensitivity) / 100.0f;
	}
}

float vectorNorm(const float v[3]) {
	return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
}

bool initializeMagPath() {
	const auto whoAmI = readImuWhoAmI();
	if (whoAmI != LSM6DSV::Regs::WhoAmI::value) {
		Serial.printf(
			"[FAIL] LSM6DSV WHOAMI mismatch: expected 0x%02X got 0x%02X\n",
			LSM6DSV::Regs::WhoAmI::value,
			whoAmI
		);
		printImuBusDiagnostics();
		return false;
	}
	Serial.println("[PASS] LSM6DSV WHOAMI matched");

	if (!imu.initialize()) {
		Serial.println("[FAIL] LSM6DSV initialization failed");
		return false;
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
			.startPolling =
				[&](uint8_t dataReg, SlimeVR::Sensors::SoftFusion::MagDataWidth dataWidth
				) { imu.startAuxPolling(dataReg, dataWidth); },
			.stopPolling = [&]() { imu.stopAuxPolling(); },
		},
		true
	);
	if (!magInit) {
		Serial.println("[FAIL] Failed to detect/init BMM350 through MagDriver");
		return false;
	}

	Serial.printf(
		"[PASS] Detected mag: %s\n",
		magDriver.getAttachedMagName() ? magDriver.getAttachedMagName() : "unknown"
	);
	magDriver.startPolling();
	return true;
}

bool readLatestImuSample(int16_t accelOut[3], int16_t gyroOut[3]) {
	bool gotAccel = false;
	bool gotGyro = false;

	for (uint8_t attempt = 0; attempt < 20; attempt++) {
		imu.bulkRead({
			[&](const auto sample[3], float) {
				accelOut[0] = sample[0];
				accelOut[1] = sample[1];
				accelOut[2] = sample[2];
				gotAccel = true;
			},
			[&](const auto sample[3], float) {
				gyroOut[0] = sample[0];
				gyroOut[1] = sample[1];
				gyroOut[2] = sample[2];
				gotGyro = true;
			},
			[](int16_t, float) {},
		});

		if (gotAccel && gotGyro) {
			return true;
		}

		delay(5);
	}

	return false;
}

bool readRawMagSample(float out[3]) {
	imu.setAuxId(kBmm350Address);

	uint8_t burst[kBmm350BurstLength] = {0};
	if (!imu.readAuxBytes(kBmm350DataRegister, sizeof(burst), burst)) {
		return false;
	}

	// Through LSM6DSV passthrough the first two bytes can be stale/idle.
	parseRawBmm350(&burst[2], out);
	return true;
}

void printStageSamples(const Stage& stage) {
	printDivider();
	Serial.printf("[STAGE] %s\n", stage.name);
	Serial.printf("[ACTION] %s\n", stage.instruction);
	Serial.printf(
		"[ACTION] Move now. Logging starts in %.1f seconds.\n",
		static_cast<float>(kMoveDelayMs) / 1000.0f
	);
	delay(kMoveDelayMs);

	for (uint8_t sampleIndex = 0; sampleIndex < kStageSamples; sampleIndex++) {
		int16_t accelRaw[3] = {0};
		int16_t gyroRaw[3] = {0};
		float magRaw[3] = {0.0f, 0.0f, 0.0f};
		float magDriverSample[3] = {0.0f, 0.0f, 0.0f};

		if (!readLatestImuSample(accelRaw, gyroRaw)) {
			Serial.printf("[FAIL] stage=%s sample=%u IMU read failed\n", stage.name, sampleIndex);
			return;
		}
		if (!readRawMagSample(magRaw)) {
			Serial.printf("[FAIL] stage=%s sample=%u raw MAG read failed\n", stage.name, sampleIndex);
			return;
		}
		if (!magDriver.readSample(magDriverSample)) {
			Serial.printf("[FAIL] stage=%s sample=%u driver MAG read failed\n", stage.name, sampleIndex);
			return;
		}

		const float accelG[3] = {
			static_cast<float>(
				static_cast<float>(accelRaw[0]) * IMUConsts<LSM6DSV>::AScale
				/ CONST_EARTH_GRAVITY
			),
			static_cast<float>(
				static_cast<float>(accelRaw[1]) * IMUConsts<LSM6DSV>::AScale
				/ CONST_EARTH_GRAVITY
			),
			static_cast<float>(
				static_cast<float>(accelRaw[2]) * IMUConsts<LSM6DSV>::AScale
				/ CONST_EARTH_GRAVITY
			),
		};
		const float gyroDps[3] = {
			static_cast<float>(gyroRaw[0]) / LSM6DSV::GyroSensitivity,
			static_cast<float>(gyroRaw[1]) / LSM6DSV::GyroSensitivity,
			static_cast<float>(gyroRaw[2]) / LSM6DSV::GyroSensitivity,
		};

		Serial.printf(
			"[IMU ] stage=%s idx=%u acc_g=(%.3f, %.3f, %.3f) gyro_dps=(%.2f, %.2f, %.2f)\n",
			stage.name,
			sampleIndex,
			accelG[0],
			accelG[1],
			accelG[2],
			gyroDps[0],
			gyroDps[1],
			gyroDps[2]
		);
		Serial.printf(
			"[MAG ] stage=%s idx=%u raw=(%.3f, %.3f, %.3f) drv=(%.3f, %.3f, %.3f) |raw|=%.3f |drv|=%.3f\n",
			stage.name,
			sampleIndex,
			magRaw[0],
			magRaw[1],
			magRaw[2],
			magDriverSample[0],
			magDriverSample[1],
			magDriverSample[2],
			vectorNorm(magRaw),
			vectorNorm(magDriverSample)
		);

		delay(kSampleIntervalMs);
	}
}

void runProbe() {
	Serial.println("BMM350 / LSM6DSV alignment probe");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	Serial.println("[INFO] accel is logged in g, gyro in dps, mag in gauss");

	if (!initializeMagPath()) {
		return;
	}

	for (const auto& stage : kStages) {
		printStageSamples(stage);
	}

	magDriver.stopPolling();
	printDivider();
	Serial.println("[PASS] Alignment probe completed");
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
