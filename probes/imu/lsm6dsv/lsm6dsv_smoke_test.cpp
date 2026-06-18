#include <Arduino.h>
#include <Wire.h>
#include <i2cscan.h>

#include "globals.h"
#include "logging/Level.cpp"
#include "logging/Logger.h"
#include "logging/Logger.cpp"
#include "I2Cdev.cpp"
#include "probe_result.h"
#include "sensorinterface/i2cimpl.h"
#include "sensors/softfusion/drivers/lsm6dsv.h"

namespace {

using SlimeVR::Logging::Logger;
using SlimeVR::Sensors::I2CImpl;
using SlimeVR::Sensors::SoftFusion::Drivers::LSM6DSV;

Logger logger{"LSM6DSVSmoke"};
I2CImpl imuRegisterInterface{LSM6DSV::Address};
LSM6DSV imu{imuRegisterInterface, logger};

void printDivider() { Serial.println("----------------------------------------"); }

void setupHostI2C() {
	Wire.begin(static_cast<int>(PIN_IMU_SDA), static_cast<int>(PIN_IMU_SCL));
	Wire.setClock(I2C_SPEED);
	delay(50);
}

bool runProbe() {
	Serial.println("LSM6DSV smoke test");
	Serial.printf("Host I2C pins: SDA=%d SCL=%d\n", PIN_IMU_SDA, PIN_IMU_SCL);
	Serial.printf("IMU address: 0x%02X\n", LSM6DSV::Address);
	printDivider();

	const auto whoAmI = imuRegisterInterface.readReg(LSM6DSV::Regs::WhoAmI::reg);
	if (whoAmI != LSM6DSV::Regs::WhoAmI::value) {
		Serial.printf(
			"[FAIL] WHOAMI mismatch: expected 0x%02X got 0x%02X\n",
			LSM6DSV::Regs::WhoAmI::value,
			whoAmI
		);
		return false;
	}
	Serial.println("[PASS] LSM6DSV WHOAMI matched");

	if (!imu.initialize()) {
		Serial.println("[FAIL] LSM6DSV initialization failed");
		return false;
	}
	Serial.println("[PASS] LSM6DSV initialized");
	printDivider();
	Serial.println("[PASS] LSM6DSV smoke test completed successfully");
	return true;
}

}  // namespace

void setup() {
	Serial.begin(115200);
	delay(2000); // sleep 2 seconds
	Serial.println();
	setupHostI2C();
	finishProbe(runProbe());
}

void loop() {
	delay(1000);
}
