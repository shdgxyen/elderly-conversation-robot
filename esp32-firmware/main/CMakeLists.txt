# The weak log-only stub and the strong AMOLED adapter must not coexist in
# the same static archive: the linker satisfies ui_board_* from whichever
# object it pulls first and may never load the adapter. Pick exactly one.
if(CONFIG_ELDER_UI_BOARD_AMOLED143C)
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
        "audio/audio_loopback.c"
        "input/buttons.c"
        "comms/usb_serial.c"
        "comms/heartbeat.c"
    INCLUDE_DIRS
        "."
        "protocol"
        "ui"
        "motion"
        "audio"
        "input"
        "comms"
    PRIV_REQUIRES
        esp_timer
        json
        esp_driver_gpio
        esp_driver_uart
        esp_driver_usb_serial_jtag
        elder_round_bsp
        lvgl__lvgl
)

target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wall
    -Wextra
    -Werror=return-type
)
