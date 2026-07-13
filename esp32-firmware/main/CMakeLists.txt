# The weak log-only stub and the strong AMOLED adapter must not coexist in
# the same static archive: the linker satisfies ui_board_* from whichever
# object it pulls first and may never load the adapter. Pick exactly one.
if(CONFIG_ELDER_UI_BOARD_AMOLED18)
    set(ELDER_UI_BOARD_SRC "ui/ui_board_amoled18.c")
else()
    set(ELDER_UI_BOARD_SRC "ui/ui_board_stub.c")
endif()

idf_component_register(
    SRCS
        "app_main.c"
        "app_state.c"
        "protocol/protocol.c"
        "ui/ui_main.c"
        "ui/ui_states.c"
        "ui/ui_faces.c"
        "${ELDER_UI_BOARD_SRC}"
        "motion/motion.c"
        "input/buttons.c"
        "comms/usb_serial.c"
        "comms/heartbeat.c"
    INCLUDE_DIRS
        "."
        "protocol"
        "ui"
        "motion"
        "input"
        "comms"
    PRIV_REQUIRES
        esp_timer
        json
        esp_driver_gpio
        esp_driver_uart
        esp_driver_usb_serial_jtag
        esp32_s3_touch_amoled_1_8
        lvgl__lvgl
        qmi8658
)

target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wall
    -Wextra
    -Werror=return-type
)
