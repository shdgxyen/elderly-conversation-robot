#include "buttons.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "sdkconfig.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct {
    gpio_num_t gpio;
    bool active_low;
    button_event_t event;
    bool stable_active;
    bool candidate_active;
    TickType_t candidate_since;
} configured_button_t;

static const char *TAG = "buttons";
static configured_button_t s_buttons[2];
static size_t s_button_count;
static button_event_handler_t s_handler;
static void *s_handler_context;
static TaskHandle_t s_task;

static bool button_read_active(const configured_button_t *button)
{
    const int level = gpio_get_level(button->gpio);
    return button->active_low ? level == 0 : level != 0;
}

#if CONFIG_ELDER_WAKE_BUTTON_ENABLED || CONFIG_ELDER_STOP_BUTTON_ENABLED
static esp_err_t add_button(int gpio_number,
                            bool active_low,
                            button_event_t event)
{
    if (gpio_number < 0 || gpio_number >= GPIO_NUM_MAX ||
        !GPIO_IS_VALID_GPIO((gpio_num_t)gpio_number) ||
        s_button_count >= (sizeof(s_buttons) / sizeof(s_buttons[0]))) {
        return ESP_ERR_INVALID_ARG;
    }

    for (size_t i = 0; i < s_button_count; ++i) {
        if (s_buttons[i].gpio == (gpio_num_t)gpio_number) {
            return ESP_ERR_INVALID_ARG;
        }
    }

    gpio_config_t config = {
        .pin_bit_mask = UINT64_C(1) << gpio_number,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
#if CONFIG_ELDER_BUTTON_INTERNAL_PULL
    config.pull_up_en = active_low ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
    config.pull_down_en = active_low ? GPIO_PULLDOWN_DISABLE : GPIO_PULLDOWN_ENABLE;
#endif
    esp_err_t result = gpio_config(&config);
    if (result != ESP_OK) {
        return result;
    }

    configured_button_t *button = &s_buttons[s_button_count++];
    button->gpio = (gpio_num_t)gpio_number;
    button->active_low = active_low;
    button->event = event;
    button->stable_active = button_read_active(button);
    button->candidate_active = button->stable_active;
    button->candidate_since = xTaskGetTickCount();
    return ESP_OK;
}
#endif

static void button_poll_task(void *argument)
{
    (void)argument;
    const TickType_t poll_ticks = pdMS_TO_TICKS(CONFIG_ELDER_BUTTON_POLL_INTERVAL_MS);
    const TickType_t debounce_ticks = pdMS_TO_TICKS(CONFIG_ELDER_BUTTON_DEBOUNCE_MS);

    while (true) {
        const TickType_t now = xTaskGetTickCount();
        for (size_t i = 0; i < s_button_count; ++i) {
            configured_button_t *button = &s_buttons[i];
            const bool active = button_read_active(button);
            if (active != button->candidate_active) {
                button->candidate_active = active;
                button->candidate_since = now;
                continue;
            }

            if (button->stable_active != button->candidate_active &&
                (now - button->candidate_since) >= debounce_ticks) {
                button->stable_active = button->candidate_active;
                if (button->stable_active) {
                    s_handler(button->event, s_handler_context);
                }
            }
        }
        vTaskDelay(poll_ticks);
    }
}

esp_err_t buttons_init(button_event_handler_t handler, void *context)
{
    if (handler == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_task != NULL || s_button_count != 0) {
        return ESP_ERR_INVALID_STATE;
    }

    s_handler = handler;
    s_handler_context = context;

#if CONFIG_ELDER_WAKE_BUTTON_ENABLED
    {
        const esp_err_t result = add_button(CONFIG_ELDER_WAKE_BUTTON_GPIO,
                                            CONFIG_ELDER_WAKE_BUTTON_ACTIVE_LOW,
                                            BUTTON_EVENT_WAKE_PRESSED);
        if (result != ESP_OK) {
            ESP_LOGE(TAG, "invalid WAKE button configuration");
            return result;
        }
    }
#endif

#if CONFIG_ELDER_STOP_BUTTON_ENABLED
    {
        const esp_err_t result = add_button(CONFIG_ELDER_STOP_BUTTON_GPIO,
                                            CONFIG_ELDER_STOP_BUTTON_ACTIVE_LOW,
                                            BUTTON_EVENT_STOP_PRESSED);
        if (result != ESP_OK) {
            ESP_LOGE(TAG, "invalid STOP button configuration");
            return result;
        }
    }
#endif

    if (s_button_count == 0) {
        ESP_LOGW(TAG, "external WAKE/STOP inputs are disabled in menuconfig");
        return ESP_OK;
    }

    if (xTaskCreate(button_poll_task,
                    "buttons",
                    CONFIG_ELDER_BUTTON_TASK_STACK_SIZE,
                    NULL,
                    6,
                    &s_task) != pdPASS) {
        s_task = NULL;
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "%u external button(s) enabled", (unsigned)s_button_count);
    return ESP_OK;
}
