#include "app_state.h"

#include <stddef.h>
#include <string.h>

#include "freertos/FreeRTOS.h"

static const char *const STATE_NAMES[APP_STATE_COUNT] = {
    [APP_STATE_BOOTING] = "BOOTING",
    [APP_STATE_IDLE] = "IDLE",
    [APP_STATE_FACE_SCANNING] = "FACE_SCANNING",
    [APP_STATE_USER_RECOGNIZED] = "USER_RECOGNIZED",
    [APP_STATE_UNKNOWN_USER] = "UNKNOWN_USER",
    [APP_STATE_LISTENING] = "LISTENING",
    [APP_STATE_THINKING] = "THINKING",
    [APP_STATE_SPEAKING] = "SPEAKING",
    [APP_STATE_CONFUSED] = "CONFUSED",
    [APP_STATE_COMFORT] = "COMFORT",
    [APP_STATE_PRIVACY_MIC_OFF] = "PRIVACY_MIC_OFF",
    [APP_STATE_PRIVACY_CAMERA_OFF] = "PRIVACY_CAMERA_OFF",
    [APP_STATE_NETWORK_ERROR] = "NETWORK_ERROR",
    [APP_STATE_API_ERROR] = "API_ERROR",
    [APP_STATE_LOW_POWER] = "LOW_POWER",
};

static portMUX_TYPE s_state_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_initialized;
static app_state_t s_current_state = APP_STATE_BOOTING;
static app_state_listener_t s_listener;
static void *s_listener_context;

static bool state_is_valid(app_state_t state)
{
    return state >= APP_STATE_BOOTING && state < APP_STATE_COUNT;
}

esp_err_t app_state_init(app_state_t initial_state)
{
    if (!state_is_valid(initial_state)) {
        return ESP_ERR_INVALID_ARG;
    }

    taskENTER_CRITICAL(&s_state_lock);
    s_current_state = initial_state;
    s_listener = NULL;
    s_listener_context = NULL;
    s_initialized = true;
    taskEXIT_CRITICAL(&s_state_lock);
    return ESP_OK;
}

esp_err_t app_state_set_listener(app_state_listener_t listener, void *context)
{
    app_state_t snapshot;

    taskENTER_CRITICAL(&s_state_lock);
    if (!s_initialized) {
        taskEXIT_CRITICAL(&s_state_lock);
        return ESP_ERR_INVALID_STATE;
    }
    s_listener = listener;
    s_listener_context = context;
    snapshot = s_current_state;
    taskEXIT_CRITICAL(&s_state_lock);

    if (listener != NULL) {
        listener(snapshot, context);
    }
    return ESP_OK;
}

esp_err_t app_state_set(app_state_t state)
{
    app_state_listener_t listener = NULL;
    void *listener_context = NULL;
    bool changed = false;

    if (!state_is_valid(state)) {
        return ESP_ERR_INVALID_ARG;
    }

    taskENTER_CRITICAL(&s_state_lock);
    if (!s_initialized) {
        taskEXIT_CRITICAL(&s_state_lock);
        return ESP_ERR_INVALID_STATE;
    }
    if (state != s_current_state) {
        s_current_state = state;
        listener = s_listener;
        listener_context = s_listener_context;
        changed = true;
    }
    taskEXIT_CRITICAL(&s_state_lock);

    if (changed && listener != NULL) {
        listener(state, listener_context);
    }
    return ESP_OK;
}

app_state_t app_state_get(void)
{
    app_state_t snapshot;

    taskENTER_CRITICAL(&s_state_lock);
    snapshot = s_current_state;
    taskEXIT_CRITICAL(&s_state_lock);
    return snapshot;
}

const char *app_state_to_string(app_state_t state)
{
    if (!state_is_valid(state)) {
        return "INVALID";
    }
    return STATE_NAMES[state];
}

bool app_state_from_string(const char *value, app_state_t *out_state)
{
    if (value == NULL || out_state == NULL) {
        return false;
    }

    for (int i = 0; i < APP_STATE_COUNT; ++i) {
        if (strcmp(value, STATE_NAMES[i]) == 0) {
            *out_state = (app_state_t)i;
            return true;
        }
    }
    return false;
}
