#include "heartbeat.h"

#include <stdbool.h>
#include <stdint.h>

#include "sdkconfig.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "protocol.h"

static const char *TAG = "heartbeat";
static TaskHandle_t s_task;

static void heartbeat_task(void *argument)
{
    (void)argument;

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(CONFIG_ELDER_HEARTBEAT_INTERVAL_MS));
        const int64_t uptime_us = esp_timer_get_time();
        const esp_err_t result = protocol_send_heartbeat((uint64_t)(uptime_us / 1000));
        if (result != ESP_OK && result != ESP_ERR_TIMEOUT) {
            ESP_LOGW(TAG, "heartbeat send failed: %s", esp_err_to_name(result));
        }
    }
}

esp_err_t heartbeat_start(void)
{
    if (s_task != NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    if (xTaskCreate(heartbeat_task,
                    "heartbeat",
                    CONFIG_ELDER_HEARTBEAT_TASK_STACK_SIZE,
                    NULL,
                    4,
                    &s_task) != pdPASS) {
        s_task = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
