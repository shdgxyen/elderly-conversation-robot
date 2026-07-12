#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "esp_err.h"

#include "app_state.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Initialize the UI facade and the optional board adapter. */
esp_err_t ui_init(void);

/** State-listener compatible entry point. */
void ui_on_state_changed(app_state_t state, void *context);

esp_err_t ui_show_state(app_state_t state);
esp_err_t ui_play_boot_animation(void);
esp_err_t ui_show_face(const char *emotion, float intensity);
esp_err_t ui_show_user(bool recognized, const char *display_name);
esp_err_t ui_show_error(const char *code, const char *message);
esp_err_t ui_set_brightness(uint8_t percent);

/** Phase 2 uses a visual/log mock until the board audio BSP is integrated. */
esp_err_t ui_play_sound(const char *name);

#ifdef __cplusplus
}
#endif
