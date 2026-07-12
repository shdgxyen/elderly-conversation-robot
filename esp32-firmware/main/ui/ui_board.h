#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#include "app_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Hardware adaptation boundary for the Waveshare display/touch/audio BSP.
 *
 * This repository intentionally ships weak, ESP_ERR_NOT_SUPPORTED stubs and
 * no guessed panel or GPIO setup. A future BSP component should provide strong
 * definitions of these functions. Calls are serialized by the UI facade, so
 * the adapter does not need an additional API-level mutex.
 *
 * String arguments are borrowed and remain valid only for the duration of the
 * call. An asynchronous LVGL/audio adapter must copy any value it queues. The
 * adapter remains responsible for any LVGL-specific lock required by its own
 * render task.
 */
esp_err_t ui_board_init(void);
esp_err_t ui_board_show_state(app_state_t state);
esp_err_t ui_board_play_boot_animation(void);
esp_err_t ui_board_show_face(const char *emotion, float intensity);
esp_err_t ui_board_show_user(bool recognized, const char *display_name);
esp_err_t ui_board_show_error(const char *code, const char *message);
esp_err_t ui_board_set_brightness(uint8_t percent);
esp_err_t ui_board_play_sound(const char *name);

#ifdef __cplusplus
}
#endif
