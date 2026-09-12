#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"
#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Start the 466x466 QSPI AMOLED and the LVGL adapter task. */
lv_display_t *bsp_display_start(void);

/** Lock LVGL before touching objects from a non-LVGL task. */
bool bsp_display_lock(uint32_t timeout_ms);

/** Release the LVGL lock. */
void bsp_display_unlock(void);

/** Set the AMOLED controller brightness in the range 0..100 percent. */
esp_err_t bsp_display_brightness_set(int brightness_percent);

#ifdef __cplusplus
}
#endif
