#include <stddef.h>

#include "sdkconfig.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "app_state.h"
#include "buttons.h"
#include "heartbeat.h"
#include "protocol.h"
#include "ui.h"
#include "usb_serial.h"

#if CONFIG_ELDER_UI_MOTION
#include "motion.h"
#endif

static const char *TAG = "app_main";

static void handle_serial_line(const char *line, size_t length, void *context)
{
    (void)context;
    const protocol_result_t result = protocol_handle_line(line, length);
    if (result != PROTOCOL_RESULT_OK) {
        ESP_LOGW(TAG, "rejected JSON line (%u bytes): %s",
                 (unsigned)length,
                 protocol_result_to_string(result));
    }
}

static void handle_button_event(button_event_t event, void *context)
{
    (void)context;
    const char *event_name = NULL;
    switch (event) {
    case BUTTON_EVENT_WAKE_PRESSED:
        event_name = "WAKE_BUTTON_PRESSED";
        break;
    case BUTTON_EVENT_STOP_PRESSED:
        event_name = "STOP_BUTTON_PRESSED";
        break;
    default:
        ESP_LOGW(TAG, "ignored unknown button event: %d", (int)event);
        return;
    }

    const esp_err_t result = protocol_send_button_event(event_name);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "failed to send %s: %s", event_name, esp_err_to_name(result));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "elder companion Phase-2 firmware starting");

    ESP_ERROR_CHECK(ui_init());
    ESP_ERROR_CHECK(app_state_init(APP_STATE_BOOTING));
    ESP_ERROR_CHECK(app_state_set_listener(ui_on_state_changed, NULL));
    ESP_ERROR_CHECK(ui_play_boot_animation());

#if CONFIG_ELDER_BOOT_ANIMATION_MS > 0
    vTaskDelay(pdMS_TO_TICKS(CONFIG_ELDER_BOOT_ANIMATION_MS));
#endif
    ESP_ERROR_CHECK(app_state_set(APP_STATE_IDLE));

    const esp_err_t serial_result = usb_serial_init(handle_serial_line, NULL);
    if (serial_result != ESP_OK) {
        ESP_LOGE(TAG, "cannot initialize JSON Lines transport: %s",
                 esp_err_to_name(serial_result));
        ESP_ERROR_CHECK(app_state_set(APP_STATE_NETWORK_ERROR));
        return;
    }

    const esp_err_t buttons_result = buttons_init(handle_button_event, NULL);
    if (buttons_result != ESP_OK) {
        ESP_LOGE(TAG, "button initialization failed: %s",
                 esp_err_to_name(buttons_result));
    }

    const esp_err_t heartbeat_result = heartbeat_start();
    if (heartbeat_result != ESP_OK) {
        ESP_LOGE(TAG, "heartbeat initialization failed: %s",
                 esp_err_to_name(heartbeat_result));
    }

#if CONFIG_ELDER_UI_MOTION
    /* Motion features are best-effort: a missing IMU only logs a warning. */
    const esp_err_t motion_result = motion_start();
    if (motion_result != ESP_OK && motion_result != ESP_ERR_NOT_FOUND) {
        ESP_LOGW(TAG, "motion init failed: %s", esp_err_to_name(motion_result));
    }
#endif

    ESP_LOGI(TAG, "ready; protocol transport=%s", usb_serial_transport_name());
}
