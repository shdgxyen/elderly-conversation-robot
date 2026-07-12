#pragma once

#include <stddef.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*usb_serial_line_handler_t)(const char *line,
                                          size_t length,
                                          void *context);

/**
 * Start the selected USB Serial/JTAG or UART transport and its JSONL framing
 * task. Despite this Phase-2 filename, the implementation is transport
 * neutral and selected through menuconfig.
 */
esp_err_t usb_serial_init(usb_serial_line_handler_t handler, void *context);

/**
 * Send exactly one JSON line. `line` must not contain CR/LF; LF is appended.
 * A transmit mutex prevents heartbeat and button tasks from interleaving.
 */
esp_err_t usb_serial_send_line(const char *line, size_t length);

const char *usb_serial_transport_name(void);

#ifdef __cplusplus
}
#endif
