#include <Arduino.h>
#include <Wire.h>
#include <i2cscan.h>

#include "globals.h"
#include "logging/Level.cpp"
#include "logging/Logger.h"
#include "logging/Logger.cpp"
#include "I2Cdev.cpp"
#include "sensorinterface/i2cimpl.h"
#include "sensors/softfusion/drivers/lsm6dsv.h"

namespace {

using SlimeVR::Logging::Logger;
using SlimeVR::Sensors::I2CImpl;
using SlimeVR::Sensors::SoftFusion::MagDataWidth;
using SlimeVR::Sensors::SoftFusion::Drivers::LSM6DSV;

constexpr uint8_t kBmm350Address = 0x14;
constexpr uint8_t kBmm350ChipIdRegister = 0x00;
constexpr uint8_t kExpectedBmm350ChipId = 0x33;

Logger logger{"BMM350Bringup"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};

void printDivider() { Serial.println("----------------------------------------"); }

void setupHostI2C() {
	Wire.begin(static_cast<int>(PIN_IMU_SDA), static_cast<int>(PIN_IMU_SCL));
	Wire.setClock(I2C_SPEED);
	delay(50);
}

bool readChipIdDummyDiscard(uint8_t& chipId) {
	uint8_t raw[3] = {0, 0, 0};
	imu.startAuxPolling(kBmm350ChipIdRegister, MagDataWidth::SixByte);
	delay(2);
	const auto bytesRead = I2Cdev::readBytes(kBmm350Address, kBmm350ChipIdRegister, 3, raw);
	imu.stopAuxPolling();

	Serial.printf(
		"Dummy-discard CHIP_ID read bytes=%d raw=[0x%02X 0x%02X 0x%02X]\n",
		bytesRead,
		raw[0],
		raw[1],
		raw[2]
	);

	if (bytesRead != 3) {
		return false;
	}

	chipId = raw[2];
	return true;
}

void runProbe() {
	Serial.println("BMM350 via LSM6DSV bring-up test");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	Serial.printf("Aux target address: 0x%02X\n", kBmm350Address);
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

	imu.setAuxId(kBmm350Address);
	uint8_t chipId = 0;
	if (!readChipIdDummyDiscard(chipId)) {
		Serial.println("[FAIL] BMM350 CHIP_ID read failed");
		return;
	}

	if (chipId != kExpectedBmm350ChipId) {
		Serial.printf(
			"[FAIL] BMM350 CHIP_ID mismatch: expected 0x%02X got 0x%02X\n",
			kExpectedBmm350ChipId,
			chipId
		);
		return;
	}

	Serial.println("[PASS] BMM350 CHIP_ID matched through LSM6DSV passthrough");
	printDivider();
	Serial.println("[PASS] BMM350 bring-up test completed successfully");
}

}  // namespace

void setup() {
	Serial.begin(115200);
	delay(2000); // sleep 2 seconds
	Serial.println();
	setupHostI2C();
	runProbe();
	Serial.println("[TEST_END]");
}

void loop() { delay(1000); }
