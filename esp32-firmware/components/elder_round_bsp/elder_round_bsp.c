/*
 * Minimal display BSP for Waveshare ESP32-S3-Touch-AMOLED-1.43C (N8R8).
 *
 * The GPIO map, QSPI panel setup and controller initialization sequence are
 * kept in sync with Waveshare's ESP-IDF 5.5.3 LVGL 9 example. Touch, audio
 * and battery support are intentionally left out of this first bring-up so
 * the expression renderer owns only the display resources it needs.
 */

#include "elder_round_bsp.h"

#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_sh8601.h"
#include "esp_log.h"
#include "esp_lv_adapter.h"

#define LCD_HOST SPI2_HOST
#define LCD_H_RES 466
#define LCD_V_RES 466

#define LCD_PIN_D0 9
#define LCD_PIN_D1 10
#define LCD_PIN_D2 11
#define LCD_PIN_D3 12
#define LCD_PIN_RST 13
#define LCD_PIN_SCK 14
#define LCD_PIN_CS 15

static const char *TAG = "round_bsp";
static esp_lcd_panel_io_handle_t s_io;
static esp_lcd_panel_handle_t s_panel;
static lv_display_t *s_display;

static const sh8601_lcd_init_cmd_t s_lcd_init_cmds[] = {
    {0xFE, (uint8_t[]){0x00}, 1, 0},
    {0xC4, (uint8_t[]){0x80}, 1, 0},
    {0x3A, (uint8_t[]){0x55}, 1, 0},
    {0x35, (uint8_t[]){0x00}, 1, 0},
    {0x53, (uint8_t[]){0x20}, 1, 0},
    {0x51, (uint8_t[]){0xFF}, 1, 0},
    {0x36, (uint8_t[]){0xC0}, 1, 0},
    {0x63, (uint8_t[]){0xFF}, 1, 0},
    {0x2A, (uint8_t[]){0x00, 0x06, 0x01, 0xD7}, 4, 0},
    {0x2B, (uint8_t[]){0x00, 0x00, 0x01, 0xD1}, 4, 0},
    {0x11, NULL, 0, 100},
    {0x29, NULL, 0, 0},
};

static void rounder_event_cb(lv_event_t *event)
{
    lv_area_t *area = (lv_area_t *)lv_event_get_param(event);
    area->x1 = (area->x1 >> 1) << 1;
    area->y1 = (area->y1 >> 1) << 1;
    area->x2 = ((area->x2 >> 1) << 1) + 1;
    area->y2 = ((area->y2 >> 1) << 1) + 1;
}

static esp_err_t panel_start(void)
{
    const spi_bus_config_t bus_config = {
        .data0_io_num = LCD_PIN_D0,
        .data1_io_num = LCD_PIN_D1,
        .sclk_io_num = LCD_PIN_SCK,
        .data2_io_num = LCD_PIN_D2,
        .data3_io_num = LCD_PIN_D3,
        .max_transfer_sz = LCD_H_RES * LCD_V_RES * sizeof(uint16_t),
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(LCD_HOST, &bus_config, SPI_DMA_CH_AUTO),
                        TAG, "initialize QSPI bus");

    const esp_lcd_panel_io_spi_config_t io_config = {
        .cs_gpio_num = LCD_PIN_CS,
        .dc_gpio_num = -1,
        .spi_mode = 0,
        .pclk_hz = 40 * 1000 * 1000,
        .trans_queue_depth = 2,
        .lcd_cmd_bits = 32,
        .lcd_param_bits = 8,
        .flags = {
            .quad_mode = true,
        },
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_spi(LCD_HOST, &io_config, &s_io),
                        TAG, "create panel IO");

    const sh8601_vendor_config_t vendor_config = {
        .init_cmds = s_lcd_init_cmds,
        .init_cmds_size = sizeof(s_lcd_init_cmds) / sizeof(s_lcd_init_cmds[0]),
        .flags = {
            .use_qspi_interface = true,
        },
    };
    const esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = LCD_PIN_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
        .vendor_config = (void *)&vendor_config,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_sh8601(s_io, &panel_config, &s_panel),
                        TAG, "create SH8601 panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "reset panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "initialize panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_set_gap(s_panel, 0x08, 0), TAG, "set panel gap");
    return ESP_OK;
}

lv_display_t *bsp_display_start(void)
{
    if (s_display != NULL) {
        return s_display;
    }
    if (panel_start() != ESP_OK) {
        return NULL;
    }

    esp_lv_adapter_config_t adapter_config = ESP_LV_ADAPTER_DEFAULT_CONFIG();
    adapter_config.task_stack_size = 8 * 1024;
    adapter_config.task_priority = 8;
    adapter_config.task_core_id = 1;
    adapter_config.stack_in_psram = true;
    if (esp_lv_adapter_init(&adapter_config) != ESP_OK) {
        ESP_LOGE(TAG, "LVGL adapter init failed");
        return NULL;
    }

    esp_lv_adapter_display_config_t display_config =
        ESP_LV_ADAPTER_DISPLAY_SPI_WITH_PSRAM_DEFAULT_CONFIG(
            s_panel, s_io, LCD_H_RES, LCD_V_RES, ESP_LV_ADAPTER_ROTATE_0);
    display_config.profile.buffer_height = 100;
    s_display = esp_lv_adapter_register_display(&display_config);
    if (s_display == NULL) {
        ESP_LOGE(TAG, "LVGL display registration failed");
        return NULL;
    }
    lv_display_add_event_cb(s_display, rounder_event_cb, LV_EVENT_INVALIDATE_AREA, NULL);

    if (esp_lv_adapter_start() != ESP_OK) {
        ESP_LOGE(TAG, "LVGL adapter start failed");
        s_display = NULL;
        return NULL;
    }
    ESP_LOGI(TAG, "466x466 round AMOLED started");
    return s_display;
}

bool bsp_display_lock(uint32_t timeout_ms)
{
    return esp_lv_adapter_lock((int32_t)timeout_ms) == ESP_OK;
}

void bsp_display_unlock(void)
{
    esp_lv_adapter_unlock();
}

esp_err_t bsp_display_brightness_set(int brightness_percent)
{
    if (s_io == NULL || s_panel == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    if (brightness_percent < 0 || brightness_percent > 100) {
        return ESP_ERR_INVALID_ARG;
    }

    const uint8_t level = (uint8_t)((brightness_percent * 255) / 100);
    uint32_t command = 0x51;
    command = ((command & 0xFFU) << 8) | (0x02U << 24);
    return esp_lcd_panel_io_tx_param(s_io, (int)command, &level, sizeof(level));
}
