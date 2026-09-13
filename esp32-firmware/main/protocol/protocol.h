#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    PROTOCOL_RESULT_OK = 0,
    PROTOCOL_RESULT_INVALID_ARGUMENT,
    PROTOCOL_RESULT_LINE_TOO_LONG,
    PROTOCOL_RESULT_INVALID_JSON,
    PROTOCOL_RESULT_INVALID_MESSAGE,
    PROTOCOL_RESULT_UNSUPPORTED_TYPE,
    PROTOCOL_RESULT_ACTION_FAILED,
} protocol_result_t;

/** Parse and dispatch one non-newline-terminated UTF-8 JSON object. */
protocol_result_t protocol_handle_line(const char *line, size_t length);

const char *protocol_result_to_string(protocol_result_t result);

/** Emit one of the ESP32 -> Pi button events listed in docs/PROTOCOL.md. */
esp_err_t protocol_send_button_event(const char *event_name);

/** Emit {"type":"heartbeat","uptime_ms":...}. */
esp_err_t protocol_send_heartbeat(uint64_t uptime_ms);

#ifdef __cplusplus
}
#endif
