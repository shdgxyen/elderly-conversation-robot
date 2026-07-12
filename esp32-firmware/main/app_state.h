#pragma once

#include <stdbool.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    APP_STATE_BOOTING = 0,
    APP_STATE_IDLE,
    APP_STATE_FACE_SCANNING,
    APP_STATE_USER_RECOGNIZED,
    APP_STATE_UNKNOWN_USER,
    APP_STATE_LISTENING,
    APP_STATE_THINKING,
    APP_STATE_SPEAKING,
    APP_STATE_CONFUSED,
    APP_STATE_COMFORT,
    APP_STATE_PRIVACY_MIC_OFF,
    APP_STATE_PRIVACY_CAMERA_OFF,
    APP_STATE_NETWORK_ERROR,
    APP_STATE_API_ERROR,
    APP_STATE_LOW_POWER,
    APP_STATE_COUNT,
} app_state_t;

typedef void (*app_state_listener_t)(app_state_t state, void *context);

/** Initialize the thread-safe state store. Safe to call once from app_main. */
esp_err_t app_state_init(app_state_t initial_state);

/**
 * Register the single UI/state observer. The observer is called immediately
 * with the current state, outside the internal critical section.
 */
esp_err_t app_state_set_listener(app_state_listener_t listener, void *context);

/** Update state and notify the observer when the value actually changes. */
esp_err_t app_state_set(app_state_t state);

/** Return a consistent snapshot of the current state. */
app_state_t app_state_get(void);

const char *app_state_to_string(app_state_t state);
bool app_state_from_string(const char *value, app_state_t *out_state);

#ifdef __cplusplus
}
#endif
