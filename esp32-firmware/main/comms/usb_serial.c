#include "usb_serial.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "sdkconfig.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
#include "driver/usb_serial_jtag.h"
#elif CONFIG_ELDER_COMMS_UART
#include "driver/uart.h"
#endif

static const char *TAG = "jsonl_serial";

static SemaphoreHandle_t s_tx_mutex;
static usb_serial_line_handler_t s_line_handler;
static void *s_line_context;
static bool s_started;

const char *usb_serial_transport_name(void)
{
#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
    return "usb-serial-jtag";
#elif CONFIG_ELDER_COMMS_UART
    return "uart";
#else
    return "unconfigured";
#endif
}

static esp_err_t transport_init(void)
{
#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
    usb_serial_jtag_driver_config_t config = {
        .tx_buffer_size = CONFIG_ELDER_USB_TX_BUFFER_SIZE,
        .rx_buffer_size = CONFIG_ELDER_USB_RX_BUFFER_SIZE,
    };
    return usb_serial_jtag_driver_install(&config);
#elif CONFIG_ELDER_COMMS_UART
    const uart_port_t port = (uart_port_t)CONFIG_ELDER_UART_PORT;
    const uart_config_t config = {
        .baud_rate = CONFIG_ELDER_UART_BAUD_RATE,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t result = uart_param_config(port, &config);
    if (result != ESP_OK) {
        return result;
    }
    result = uart_set_pin(port,
                          CONFIG_ELDER_UART_TX_GPIO,
                          CONFIG_ELDER_UART_RX_GPIO,
                          UART_PIN_NO_CHANGE,
                          UART_PIN_NO_CHANGE);
    if (result != ESP_OK) {
        return result;
    }
    return uart_driver_install(port,
                               CONFIG_ELDER_UART_RX_BUFFER_SIZE,
                               CONFIG_ELDER_UART_TX_BUFFER_SIZE,
                               0,
                               NULL,
                               0);
#else
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

static void transport_deinit(void)
{
#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
    usb_serial_jtag_driver_uninstall();
#elif CONFIG_ELDER_COMMS_UART
    uart_driver_delete((uart_port_t)CONFIG_ELDER_UART_PORT);
#endif
}

static int transport_read(uint8_t *buffer, size_t length, TickType_t timeout)
{
#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
    return usb_serial_jtag_read_bytes(buffer, (uint32_t)length, timeout);
#elif CONFIG_ELDER_COMMS_UART
    return uart_read_bytes((uart_port_t)CONFIG_ELDER_UART_PORT,
                           buffer,
                           (uint32_t)length,
                           timeout);
#else
    (void)buffer;
    (void)length;
    (void)timeout;
    return -1;
#endif
}

static int transport_write(const uint8_t *buffer, size_t length, TickType_t timeout)
{
#if CONFIG_ELDER_COMMS_USB_SERIAL_JTAG
    return usb_serial_jtag_write_bytes(buffer, length, timeout);
#elif CONFIG_ELDER_COMMS_UART
    (void)timeout;
    return uart_write_bytes((uart_port_t)CONFIG_ELDER_UART_PORT,
                            (const char *)buffer,
                            length);
#else
    (void)buffer;
    (void)length;
    (void)timeout;
    return -1;
#endif
}

static esp_err_t write_all(const uint8_t *data, size_t length)
{
    size_t written = 0;
    const TickType_t timeout = pdMS_TO_TICKS(CONFIG_ELDER_COMMS_TX_TIMEOUT_MS);

    while (written < length) {
        const int result = transport_write(data + written, length - written, timeout);
        if (result < 0) {
            return ESP_FAIL;
        }
        if (result == 0) {
            return ESP_ERR_TIMEOUT;
        }
        written += (size_t)result;
    }
    return ESP_OK;
}

static void serial_receive_task(void *argument)
{
    (void)argument;
    uint8_t chunk[128];
    /* One extra byte permits a CR terminator after a maximum-sized payload. */
    char line[CONFIG_ELDER_JSON_LINE_MAX_LENGTH + 1];
    size_t line_length = 0;
    bool dropping_oversized_line = false;

    while (true) {
        const int received = transport_read(chunk,
                                            sizeof(chunk),
                                            pdMS_TO_TICKS(100));
        if (received < 0) {
            ESP_LOGE(TAG, "%s receive failed", usb_serial_transport_name());
            vTaskDelay(pdMS_TO_TICKS(250));
            continue;
        }

        for (int i = 0; i < received; ++i) {
            const uint8_t byte = chunk[i];
            if (byte == '\n') {
                if (dropping_oversized_line) {
                    ESP_LOGW(TAG, "discarded JSON line longer than %d bytes",
                             CONFIG_ELDER_JSON_LINE_MAX_LENGTH);
                } else {
                    if (line_length > 0 && line[line_length - 1] == '\r') {
                        --line_length;
                    }
                    if (line_length > CONFIG_ELDER_JSON_LINE_MAX_LENGTH) {
                        ESP_LOGW(TAG, "discarded JSON line longer than %d bytes",
                                 CONFIG_ELDER_JSON_LINE_MAX_LENGTH);
                    } else if (line_length > 0) {
                        s_line_handler(line, line_length, s_line_context);
                    }
                }
                line_length = 0;
                dropping_oversized_line = false;
                continue;
            }

            if (dropping_oversized_line) {
                continue;
            }
            if (line_length >= sizeof(line)) {
                line_length = 0;
                dropping_oversized_line = true;
                continue;
            }
            line[line_length++] = (char)byte;
        }
    }
}

esp_err_t usb_serial_init(usb_serial_line_handler_t handler, void *context)
{
    if (handler == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_started) {
        return ESP_ERR_INVALID_STATE;
    }

    s_tx_mutex = xSemaphoreCreateMutex();
    if (s_tx_mutex == NULL) {
        return ESP_ERR_NO_MEM;
    }

    esp_err_t result = transport_init();
    if (result != ESP_OK) {
        vSemaphoreDelete(s_tx_mutex);
        s_tx_mutex = NULL;
        return result;
    }

    s_line_handler = handler;
    s_line_context = context;
    s_started = true;
    if (xTaskCreate(serial_receive_task,
                    "jsonl_rx",
                    CONFIG_ELDER_COMMS_RX_TASK_STACK_SIZE,
                    NULL,
                    CONFIG_ELDER_COMMS_RX_TASK_PRIORITY,
                    NULL) != pdPASS) {
        s_started = false;
        s_line_handler = NULL;
        s_line_context = NULL;
        transport_deinit();
        vSemaphoreDelete(s_tx_mutex);
        s_tx_mutex = NULL;
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "JSON Lines transport ready: %s", usb_serial_transport_name());
    return ESP_OK;
}

esp_err_t usb_serial_send_line(const char *line, size_t length)
{
    if (line == NULL || length == 0 ||
        length > CONFIG_ELDER_JSON_LINE_MAX_LENGTH ||
        memchr(line, '\n', length) != NULL ||
        memchr(line, '\r', length) != NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!s_started || s_tx_mutex == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    if (xSemaphoreTake(s_tx_mutex,
                       pdMS_TO_TICKS(CONFIG_ELDER_COMMS_TX_TIMEOUT_MS)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }

    esp_err_t result = write_all((const uint8_t *)line, length);
    if (result == ESP_OK) {
        static const uint8_t newline = '\n';
        result = write_all(&newline, 1);
    }
    xSemaphoreGive(s_tx_mutex);
    return result;
}
