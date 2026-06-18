#pragma once

#include <Arduino.h>

// Shared verdict reporting for integration probes.
//
// Verification tooling (see slimevr-flasher) treats a probe as PASS only when it
// observes [VERIFY_PASS] before [TEST_END]. Any other outcome ([VERIFY_FAIL],
// a missing marker, or a serial timeout) is treated as a failure. Probes should
// return a single bool from their run function and hand it to finishProbe().
inline void finishProbe(bool ok) {
	Serial.println(ok ? "[VERIFY_PASS]" : "[VERIFY_FAIL]");
	Serial.println("[TEST_END]");
}
