#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Start the Waveshare ESP32-S3-Touch-AMOLED-1.43C audio verification task.
 *
 * One record/replay cycle runs automatically after startup. Later cycles are
 * triggered by a debounced press of the on-board BOOT key (GPIO0).
 */
esp_err_t audio_loopback_start(void);

#ifdef __cplusplus
}
#endif
