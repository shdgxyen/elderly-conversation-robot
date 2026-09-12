idf_component_register(
    SRCS "elder_round_bsp.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES
        driver
        esp_lcd
        espressif__esp_lcd_sh8601
        espressif__esp_lvgl_adapter
        lvgl__lvgl
)
