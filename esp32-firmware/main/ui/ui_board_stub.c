#include "ui_board.h"

/*
 * Weak functions make the Phase-2 firmware link without a vendor BSP. A
 * future component can replace any function with a strong implementation.
 */

__attribute__((weak)) esp_err_t ui_board_init(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_show_state(app_state_t state)
{
    (void)state;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_play_boot_animation(void)
{
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_show_face(const char *emotion, float intensity)
{
    (void)emotion;
    (void)intensity;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_show_user(bool recognized, const char *display_name)
{
    (void)recognized;
    (void)display_name;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_show_error(const char *code, const char *message)
{
    (void)code;
    (void)message;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_set_brightness(uint8_t percent)
{
    (void)percent;
    return ESP_ERR_NOT_SUPPORTED;
}

__attribute__((weak)) esp_err_t ui_board_play_sound(const char *name)
{
    (void)name;
    return ESP_ERR_NOT_SUPPORTED;
}
