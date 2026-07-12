#include "ui.h"

#include <stddef.h>

#include "esp_log.h"

#include "ui_board.h"
#include "ui_internal.h"

static const char *TAG = "ui_face";

esp_err_t ui_show_face(const char *emotion, float intensity)
{
    if (emotion == NULL || intensity < 0.0f || intensity > 1.0f) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_show_face(emotion, intensity);
    if (ui_internal_uses_log_fallback() || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "face emotion=%s intensity=%.2f", emotion, (double)intensity);
    }
    ui_internal_unlock();
    return ui_internal_finish_call("show face", result);
}
