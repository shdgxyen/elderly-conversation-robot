#pragma once

#include "sdkconfig.h"

#ifdef __cplusplus
extern "C" {
#endif

#if CONFIG_ELDER_UI_BOARD_AMOLED143C

/**
 * Motion hooks for the AMOLED-1.8 face adapter. Both functions are
 * thread-safe: they only publish values consumed by an LVGL-side timer,
 * so they may be called from any FreeRTOS task without display locking.
 */

/** Eye gaze target, each axis in -1.0 .. 1.0 (0 = center). */
void ui_amoled18_set_gaze(float x, float y);

/** Report a strong shake; the face plays a short dizzy animation when the
 *  current state allows it (quiet states only). */
void ui_amoled18_notify_shake(void);

#endif /* CONFIG_ELDER_UI_BOARD_AMOLED143C */

#ifdef __cplusplus
}
#endif
