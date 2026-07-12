#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    BUTTON_EVENT_WAKE_PRESSED = 0,
    BUTTON_EVENT_STOP_PRESSED,
} button_event_t;

typedef void (*button_event_handler_t)(button_event_t event, void *context);

/**
 * Configure explicitly enabled button GPIOs and start a debounced polling
 * task. With the default menuconfig both inputs are disabled and this is a
 * safe no-op; no board pin is guessed.
 */
esp_err_t buttons_init(button_event_handler_t handler, void *context);

#ifdef __cplusplus
}
#endif
