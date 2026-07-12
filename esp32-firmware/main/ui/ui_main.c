#include "ui.h"

#include <inttypes.h>
#include <stddef.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "ui_board.h"
#include "ui_internal.h"

static const char *TAG = "ui";
static SemaphoreHandle_t s_ui_mutex;
static bool s_log_fallback = true;

esp_err_t ui_init(void)
{
    if (s_ui_mutex != NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    s_ui_mutex = xSemaphoreCreateMutex();
    if (s_ui_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }

    const esp_err_t result = ui_board_init();
    if (result == ESP_OK) {
        s_log_fallback = false;
        ESP_LOGI(TAG, "board UI adapter initialized");
        return ESP_OK;
    }
    if (result == ESP_ERR_NOT_SUPPORTED) {
        s_log_fallback = true;
        ESP_LOGW(TAG, "no display BSP linked; using deterministic log fallback");
        return ESP_OK;
    }

    ESP_LOGE(TAG, "board UI initialization failed: %s", esp_err_to_name(result));
    return result;
}

esp_err_t ui_internal_lock(void)
{
    if (s_ui_mutex == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    if (xSemaphoreTake(s_ui_mutex, pdMS_TO_TICKS(1000)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

void ui_internal_unlock(void)
{
    if (s_ui_mutex != NULL) {
        xSemaphoreGive(s_ui_mutex);
    }
}

bool ui_internal_uses_log_fallback(void)
{
    return s_log_fallback;
}

esp_err_t ui_internal_finish_call(const char *operation, esp_err_t result)
{
    if (result == ESP_OK || result == ESP_ERR_NOT_SUPPORTED) {
        return ESP_OK;
    }
    ESP_LOGE(TAG, "%s failed: %s", operation, esp_err_to_name(result));
    return result;
}

esp_err_t ui_show_user(bool recognized, const char *display_name)
{
    if (display_name == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_show_user(recognized, display_name);
    if (s_log_fallback || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "user recognized=%s display_name=%s",
                 recognized ? "true" : "false", display_name);
    }
    ui_internal_unlock();
    return ui_internal_finish_call("show user", result);
}

esp_err_t ui_show_error(const char *code, const char *message)
{
    if (code == NULL || message == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_show_error(code, message);
    if (s_log_fallback || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGW(TAG, "error code=%s message=%s", code, message);
    }
    ui_internal_unlock();
    return ui_internal_finish_call("show error", result);
}

esp_err_t ui_set_brightness(uint8_t percent)
{
    if (percent > 100) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_set_brightness(percent);
    if (s_log_fallback || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "display brightness=%" PRIu8 "%%", percent);
    }
    ui_internal_unlock();
    return ui_internal_finish_call("set brightness", result);
}

esp_err_t ui_play_sound(const char *name)
{
    if (name == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    esp_err_t result = ui_internal_lock();
    if (result != ESP_OK) {
        return result;
    }
    result = ui_board_play_sound(name);
    if (s_log_fallback || result == ESP_ERR_NOT_SUPPORTED) {
        ESP_LOGI(TAG, "mock sound=%s", name);
    }
    ui_internal_unlock();
    return ui_internal_finish_call("play sound", result);
}
