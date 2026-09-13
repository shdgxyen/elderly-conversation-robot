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

/**
 * Queue one playback of the built-in speaker test clip (Chinese voice prompt,
 * ascending chime and a 150 Hz-6 kHz sweep, about 13 s). It starts once any
 * record/replay cycle in progress has finished.
 */
esp_err_t audio_loopback_request_speaker_test(void);

#ifdef __cplusplus
}
#endif
