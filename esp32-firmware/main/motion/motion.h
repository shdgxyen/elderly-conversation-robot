#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Start the QMI8658 IMU sampling task (gaze tracking + shake detection).
 * Feeds the AMOLED-1.8 face adapter through its thread-safe motion hooks.
 * Returns ESP_ERR_NOT_FOUND when no IMU responds on the shared I2C bus;
 * the firmware keeps running without motion features in that case.
 */
esp_err_t motion_start(void);

#ifdef __cplusplus
}
#endif
