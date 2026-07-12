#include "ui.h"

#include "esp_log.h"

#include "ui_board.h"
#include "ui_internal.h"

static const char *TAG = "ui_state";

esp_err_t ui_show_state(app_state_t state)
{
    if (state < APP_STATE_BOOTING || state >= APP_STATE_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_show_state(state);
    if (ui_internal_uses_log_fallback() || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "state=%s", app_state_to_string(state));
    }
    ui_internal_unlock();
    return ui_internal_finish_call("show state", result);
}

void ui_on_state_changed(app_state_t state, void *context)
{
    (void)context;
    const esp_err_t result = ui_show_state(state);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "state render failed: %s", esp_err_to_name(result));
    }
}

esp_err_t ui_play_boot_animation(void)
{
    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_play_boot_animation();
    if (ui_internal_uses_log_fallback() || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "boot animation (log fallback)");
    }
    ui_internal_unlock();
    return ui_internal_finish_call("play boot animation", result);
}
