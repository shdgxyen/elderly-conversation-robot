#pragma once

#include <stdbool.h>

#include "esp_err.h"

esp_err_t ui_internal_lock(void);
void ui_internal_unlock(void);
bool ui_internal_uses_log_fallback(void);

/** Normalize adapter results and report real hardware failures. */
esp_err_t ui_internal_finish_call(const char *operation, esp_err_t result);
