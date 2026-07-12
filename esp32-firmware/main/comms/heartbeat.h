#pragma once

#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Start the periodic JSON heartbeat task. */
esp_err_t heartbeat_start(void);

#ifdef __cplusplus
}
#endif
