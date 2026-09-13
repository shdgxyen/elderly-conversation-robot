/*
 * Strong ui_board_* implementation for the Waveshare ESP32-S3-Touch-AMOLED-
 * 1.43C (466x466 round panel). Rendering is done with LVGL 9 through the
 * project's minimal display BSP based on Waveshare's official example.
 *
 * Design rule: every coordinate derives from s_d, the diameter of a circular
 * "face canvas" (min(width, height)). All expression elements stay inside
 * that circle, so this file ports to the round 466x466 1.43C target without
 * layout changes.
 *
 * Threading: ui_* facade calls arrive serialized (one mutex) but from a
 * non-LVGL task, so every LVGL touch here is wrapped in bsp_display_lock().
 * LVGL timers/animations run inside the LVGL task and need no lock.
 */

#include "sdkconfig.h"

#if CONFIG_ELDER_UI_BOARD_AMOLED143C

#include <string.h>

#include "esp_err.h"
#include "esp_log.h"

#include "elder_round_bsp.h"
#include "lvgl.h"

#include "app_state.h"
#include "ui_board.h"
#include "ui_board_amoled143c.h"

static const char *TAG = "ui_round143c";

#if LV_VERSION_CHECK(9, 1, 0)
#define face_clear_flag lv_obj_remove_flag
#else
#define face_clear_flag lv_obj_clear_flag
#endif

/* --- geometry ----------------------------------------------------------- */

static int32_t s_d; /* face circle diameter in px */
#define FD(pct) ((s_d * (pct)) / 100)

/* --- widgets ------------------------------------------------------------ */

static lv_display_t *s_disp;
static lv_obj_t *s_face;    /* circular canvas */
static lv_obj_t *s_eye_l;
static lv_obj_t *s_eye_r;
static lv_obj_t *s_smile;   /* curved mouth (smile / frown), lv_arc */
static lv_obj_t *s_flat;    /* flat mouth, rounded bar */
static lv_obj_t *s_open;    /* round/open mouth (listening, speaking) */
static lv_obj_t *s_status;  /* large symbol / thinking dots */
static lv_obj_t *s_caption; /* CJK text: names, error messages */
static lv_obj_t *s_star[3]; /* orbiting sparks for the dizzy animation */
static lv_obj_t *s_hl_l;    /* eye highlight dots (clipped inside the eyes) */
static lv_obj_t *s_hl_r;
static lv_obj_t *s_surprise_nose;
static lv_obj_t *s_surprise_inner;
static lv_obj_t *s_alert_bar[3];
static lv_obj_t *s_alert_dot[3];

static lv_timer_t *s_blink_timer;
static lv_timer_t *s_think_timer;
static lv_timer_t *s_surprise_stage_timer;
static lv_timer_t *s_surprise_end_timer;
static bool s_blink_enabled;
static int s_think_phase;
static bool s_dimmed;
static app_state_t s_surprise_return_state = APP_STATE_IDLE;

/* Motion interactivity (fed by the IMU task through the public hooks).
 * Gaze values are stored as milli-units so 32-bit writes stay atomic. */
static app_state_t s_current_state = APP_STATE_BOOTING;
static volatile int32_t s_gaze_x_mil;
static volatile int32_t s_gaze_y_mil;
static volatile bool s_shake_pending;
static bool s_dizzy_active;
static lv_timer_t *s_motion_timer;
static lv_timer_t *s_dizzy_end_timer;

static int32_t s_eye_w, s_eye_h; /* current nominal eye size */

typedef enum {
    MOUTH_SMILE,
    MOUTH_SAD,
    MOUTH_FLAT,
    MOUTH_O,     /* small round mouth */
    MOUTH_OPEN,  /* animated talking mouth */
    MOUTH_NONE,
} mouth_mode_t;

static void apply_state(app_state_t state);

/* --- small helpers (LVGL task or under bsp_display_lock) ---------------- */

static void anim_set_height(void *obj, int32_t v)
{
    lv_obj_set_height((lv_obj_t *)obj, v);
}

static void anim_set_width(void *obj, int32_t v)
{
    lv_obj_set_width((lv_obj_t *)obj, v);
}

static void anim_translate_x(void *obj, int32_t v)
{
    lv_obj_set_style_translate_x((lv_obj_t *)obj, v, 0);
}

static void anim_translate_y(void *obj, int32_t v)
{
    lv_obj_set_style_translate_y((lv_obj_t *)obj, v, 0);
}

static void restore_standard_canvas(void)
{
    lv_obj_set_style_bg_color(lv_screen_active(), lv_color_black(), 0);
    lv_obj_set_style_bg_color(s_face, lv_color_hex(0x18222E), 0);
    lv_obj_set_style_bg_grad_color(s_face, lv_color_hex(0x0A0E13), 0);
    lv_obj_set_style_bg_grad_dir(s_face, LV_GRAD_DIR_VER, 0);
    face_clear_flag(s_hl_l, LV_OBJ_FLAG_HIDDEN);
    face_clear_flag(s_hl_r, LV_OBJ_FLAG_HIDDEN);

    lv_obj_add_flag(s_surprise_nose, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_surprise_inner, LV_OBJ_FLAG_HIDDEN);
    for (size_t i = 0; i < 3; i++) {
        lv_obj_add_flag(s_alert_bar[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_alert_dot[i], LV_OBJ_FLAG_HIDDEN);
    }
}

static void blink_timer_cb(lv_timer_t *timer)
{
    (void)timer;
    if (!s_blink_enabled) {
        return;
    }
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_values(&a, s_eye_h, FD(2));
    lv_anim_set_duration(&a, 90);
    lv_anim_set_playback_duration(&a, 120);
    lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
    lv_anim_set_exec_cb(&a, anim_set_height);
    lv_anim_set_var(&a, s_eye_l);
    lv_anim_start(&a);
    lv_anim_set_var(&a, s_eye_r);
    lv_anim_start(&a);
}

static void think_timer_cb(lv_timer_t *timer)
{
    (void)timer;
    static const char *dots[] = {".", "..", "..."};
    s_think_phase = (s_think_phase + 1) % 3;
    lv_label_set_text(s_status, dots[s_think_phase]);
}

static void stop_dynamics(void)
{
    s_blink_enabled = false;
    if (s_think_timer != NULL) {
        lv_timer_delete(s_think_timer);
        s_think_timer = NULL;
    }
    if (s_surprise_stage_timer != NULL) {
        lv_timer_delete(s_surprise_stage_timer);
        s_surprise_stage_timer = NULL;
    }
    if (s_surprise_end_timer != NULL) {
        lv_timer_delete(s_surprise_end_timer);
        s_surprise_end_timer = NULL;
    }
    lv_anim_delete(s_eye_l, NULL);
    lv_anim_delete(s_eye_r, NULL);
    lv_anim_delete(s_open, NULL);
    lv_anim_delete(s_face, NULL);
    lv_obj_set_style_translate_x(s_eye_l, 0, 0);
    lv_obj_set_style_translate_x(s_eye_r, 0, 0);
    lv_obj_set_style_translate_y(s_eye_l, 0, 0);
    lv_obj_set_style_translate_y(s_eye_r, 0, 0);
    lv_obj_set_style_translate_x(s_face, 0, 0);
    lv_obj_set_style_translate_y(s_face, 0, 0);
    lv_obj_set_style_translate_y(s_open, 0, 0);
    for (size_t i = 0; i < 3; i++) {
        if (s_star[i] != NULL) {
            lv_anim_delete(s_star[i], NULL);
            lv_obj_add_flag(s_star[i], LV_OBJ_FLAG_HIDDEN);
        }
        if (s_alert_bar[i] != NULL) {
            lv_anim_delete(s_alert_bar[i], NULL);
        }
    }
    restore_standard_canvas();
}

static void set_eyes(int32_t w, int32_t h, int32_t dy, lv_color_t color)
{
    s_eye_w = w;
    s_eye_h = h;
    lv_obj_set_size(s_eye_l, w, h);
    lv_obj_set_size(s_eye_r, w, h);
    lv_obj_align(s_eye_l, LV_ALIGN_CENTER, -FD(22), dy);
    lv_obj_align(s_eye_r, LV_ALIGN_CENTER, FD(22), dy);

    /* Subtle vertical sheen: base color on top fading darker below. */
    const lv_color_t shade = lv_color_darken(color, 70);
    lv_obj_t *eyes[] = {s_eye_l, s_eye_r};
    for (size_t i = 0; i < 2; i++) {
        lv_obj_set_style_bg_color(eyes[i], color, 0);
        lv_obj_set_style_bg_grad_color(eyes[i], shade, 0);
        lv_obj_set_style_bg_grad_dir(eyes[i], LV_GRAD_DIR_VER, 0);
    }
}

static void set_mouth(mouth_mode_t mode, lv_color_t color, int32_t weight)
{
    lv_obj_add_flag(s_smile, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_flat, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_open, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_surprise_inner, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_border_width(s_open, 0, 0);
    lv_obj_set_style_bg_opa(s_open, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(s_open, LV_RADIUS_CIRCLE, 0);

    switch (mode) {
    case MOUTH_SMILE:
        lv_arc_set_bg_angles(s_smile, 25, 155);
        lv_obj_align(s_smile, LV_ALIGN_CENTER, 0, FD(6));
        lv_obj_set_style_arc_color(s_smile, color, LV_PART_MAIN);
        lv_obj_set_style_arc_width(s_smile, weight, LV_PART_MAIN);
        face_clear_flag(s_smile, LV_OBJ_FLAG_HIDDEN);
        break;
    case MOUTH_SAD:
        lv_arc_set_bg_angles(s_smile, 205, 335);
        lv_obj_align(s_smile, LV_ALIGN_CENTER, 0, FD(30));
        lv_obj_set_style_arc_color(s_smile, color, LV_PART_MAIN);
        lv_obj_set_style_arc_width(s_smile, weight, LV_PART_MAIN);
        face_clear_flag(s_smile, LV_OBJ_FLAG_HIDDEN);
        break;
    case MOUTH_FLAT:
        lv_obj_set_size(s_flat, FD(24), weight);
        lv_obj_align(s_flat, LV_ALIGN_CENTER, 0, FD(20));
        lv_obj_set_style_bg_color(s_flat, color, 0);
        face_clear_flag(s_flat, LV_OBJ_FLAG_HIDDEN);
        break;
    case MOUTH_O:
        lv_obj_set_size(s_open, FD(9), FD(9));
        lv_obj_align(s_open, LV_ALIGN_CENTER, 0, FD(20));
        lv_obj_set_style_bg_color(s_open, color, 0);
        face_clear_flag(s_open, LV_OBJ_FLAG_HIDDEN);
        break;
    case MOUTH_OPEN: {
        lv_obj_set_size(s_open, FD(16), FD(6));
        lv_obj_align(s_open, LV_ALIGN_CENTER, 0, FD(20));
        lv_obj_set_style_bg_color(s_open, color, 0);
        face_clear_flag(s_open, LV_OBJ_FLAG_HIDDEN);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_var(&a, s_open);
        lv_anim_set_values(&a, FD(4), FD(14));
        lv_anim_set_duration(&a, 180);
        lv_anim_set_playback_duration(&a, 160);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
        lv_anim_set_exec_cb(&a, anim_set_height);
        lv_anim_start(&a);
        break;
    }
    case MOUTH_NONE:
    default:
        break;
    }
}

static void set_texts(const char *symbol, const char *caption)
{
    if (symbol != NULL) {
        lv_label_set_text(s_status, symbol);
        face_clear_flag(s_status, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_status, LV_OBJ_FLAG_HIDDEN);
    }
    if (caption != NULL) {
        lv_label_set_text(s_caption, caption);
        face_clear_flag(s_caption, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_caption, LV_OBJ_FLAG_HIDDEN);
    }
}

/* --- palette ------------------------------------------------------------ */

static lv_color_t col_eye(void)    { return lv_color_hex(0xEAF6FF); }
static lv_color_t col_accent(void) { return lv_color_hex(0x37C8F5); }
static lv_color_t col_warm(void)   { return lv_color_hex(0xFFC48A); }
static lv_color_t col_alert(void)  { return lv_color_hex(0xFF8A7A); }
static lv_color_t col_cream(void)  { return lv_color_hex(0xF4F1E7); }
static lv_color_t col_ink(void)    { return lv_color_hex(0x11100E); }
static lv_color_t col_yellow(void) { return lv_color_hex(0xF6C83F); }
static lv_color_t col_coral(void)  { return lv_color_hex(0xE9937E); }

/* --- expression presets -------------------------------------------------- */

static void show_alert_marks(size_t count, bool large)
{
    const int32_t start_x = large ? FD(15) : FD(12);
    const int32_t gap = large ? FD(8) : FD(7);
    const int32_t top_y = large ? -FD(28) : -FD(25);
    const int32_t bar_w = large ? FD(4) : FD(3);
    const int32_t bar_h = large ? FD(13) : FD(10);
    const int32_t dot_d = large ? FD(4) : FD(3);

    for (size_t i = 0; i < 3; i++) {
        lv_anim_delete(s_alert_bar[i], NULL);
        if (i >= count) {
            lv_obj_add_flag(s_alert_bar[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(s_alert_dot[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }

        const int32_t x = start_x + (int32_t)i * gap;
        lv_obj_set_size(s_alert_bar[i], bar_w, bar_h);
        lv_obj_align(s_alert_bar[i], LV_ALIGN_CENTER, x, top_y);
        lv_obj_set_style_bg_color(s_alert_bar[i], col_yellow(), 0);
        face_clear_flag(s_alert_bar[i], LV_OBJ_FLAG_HIDDEN);

        lv_obj_set_size(s_alert_dot[i], dot_d, dot_d);
        lv_obj_align(s_alert_dot[i], LV_ALIGN_CENTER, x, top_y + bar_h);
        lv_obj_set_style_bg_color(s_alert_dot[i], col_yellow(), 0);
        face_clear_flag(s_alert_dot[i], LV_OBJ_FLAG_HIDDEN);

        lv_anim_t pulse;
        lv_anim_init(&pulse);
        lv_anim_set_var(&pulse, s_alert_bar[i]);
        lv_anim_set_values(&pulse, bar_h - FD(2), bar_h + FD(2));
        lv_anim_set_duration(&pulse, 220);
        lv_anim_set_playback_duration(&pulse, 220);
        lv_anim_set_repeat_count(&pulse, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_delay(&pulse, (uint32_t)i * 70);
        lv_anim_set_path_cb(&pulse, lv_anim_path_ease_in_out);
        lv_anim_set_exec_cb(&pulse, anim_set_height);
        lv_anim_start(&pulse);
    }
}

static void surprise_small(void)
{
    lv_obj_set_style_bg_color(lv_screen_active(), col_cream(), 0);
    lv_obj_set_style_bg_color(s_face, col_cream(), 0);
    lv_obj_set_style_bg_grad_color(s_face, col_cream(), 0);
    lv_obj_set_style_bg_grad_dir(s_face, LV_GRAD_DIR_NONE, 0);
    lv_obj_add_flag(s_hl_l, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_hl_r, LV_OBJ_FLAG_HIDDEN);

    set_eyes(FD(6), FD(2), -FD(15), col_ink());
    lv_obj_align(s_eye_l, LV_ALIGN_CENTER, -FD(14), -FD(15));
    lv_obj_align(s_eye_r, LV_ALIGN_CENTER, FD(14), -FD(15));

    lv_obj_set_size(s_surprise_nose, FD(4), FD(4));
    lv_obj_align(s_surprise_nose, LV_ALIGN_CENTER, 0, -FD(4));
    face_clear_flag(s_surprise_nose, LV_OBJ_FLAG_HIDDEN);

    set_mouth(MOUTH_NONE, col_ink(), 0);
    lv_obj_set_size(s_open, FD(8), FD(16));
    lv_obj_align(s_open, LV_ALIGN_CENTER, 0, FD(13));
    lv_obj_set_style_bg_color(s_open, col_cream(), 0);
    lv_obj_set_style_border_color(s_open, col_ink(), 0);
    lv_obj_set_style_border_width(s_open, FD(2), 0);
    lv_obj_set_style_radius(s_open, FD(3), 0);
    face_clear_flag(s_open, LV_OBJ_FLAG_HIDDEN);

    set_texts(NULL, NULL);
    show_alert_marks(3, false);

    lv_anim_t eye_open;
    lv_anim_init(&eye_open);
    lv_anim_set_values(&eye_open, FD(2), FD(14));
    lv_anim_set_duration(&eye_open, 320);
    lv_anim_set_path_cb(&eye_open, lv_anim_path_overshoot);
    lv_anim_set_exec_cb(&eye_open, anim_set_height);
    lv_anim_set_var(&eye_open, s_eye_l);
    lv_anim_start(&eye_open);
    lv_anim_set_delay(&eye_open, 45);
    lv_anim_set_var(&eye_open, s_eye_r);
    lv_anim_start(&eye_open);

    lv_anim_t mouth_wake;
    lv_anim_init(&mouth_wake);
    lv_anim_set_var(&mouth_wake, s_open);
    lv_anim_set_values(&mouth_wake, FD(8), FD(18));
    lv_anim_set_duration(&mouth_wake, 360);
    lv_anim_set_path_cb(&mouth_wake, lv_anim_path_overshoot);
    lv_anim_set_exec_cb(&mouth_wake, anim_set_width);
    lv_anim_start(&mouth_wake);

    lv_anim_t bounce;
    lv_anim_init(&bounce);
    lv_anim_set_var(&bounce, s_face);
    lv_anim_set_values(&bounce, FD(4), 0);
    lv_anim_set_duration(&bounce, 420);
    lv_anim_set_path_cb(&bounce, lv_anim_path_overshoot);
    lv_anim_set_exec_cb(&bounce, anim_translate_y);
    lv_anim_start(&bounce);
}

static void surprise_large(void)
{
    set_eyes(FD(8), FD(22), -FD(14), col_ink());
    lv_obj_align(s_eye_l, LV_ALIGN_CENTER, -FD(16), -FD(14));
    lv_obj_align(s_eye_r, LV_ALIGN_CENTER, FD(16), -FD(14));

    lv_obj_set_size(s_surprise_nose, FD(4), FD(4));
    lv_obj_align(s_surprise_nose, LV_ALIGN_CENTER, 0, -FD(2));

    lv_anim_delete(s_open, NULL);
    lv_obj_set_width(s_open, FD(23));
    lv_obj_align(s_open, LV_ALIGN_CENTER, 0, FD(18));
    lv_obj_set_style_bg_color(s_open, col_ink(), 0);
    lv_obj_set_style_border_width(s_open, 0, 0);
    lv_obj_set_style_radius(s_open, LV_RADIUS_CIRCLE, 0);
    face_clear_flag(s_open, LV_OBJ_FLAG_HIDDEN);

    lv_obj_set_size(s_surprise_inner, FD(11), FD(17));
    lv_obj_align(s_surprise_inner, LV_ALIGN_CENTER, 0, FD(3));
    face_clear_flag(s_surprise_inner, LV_OBJ_FLAG_HIDDEN);

    lv_anim_t mouth_pop;
    lv_anim_init(&mouth_pop);
    lv_anim_set_var(&mouth_pop, s_open);
    lv_anim_set_values(&mouth_pop, FD(14), FD(30));
    lv_anim_set_duration(&mouth_pop, 300);
    lv_anim_set_path_cb(&mouth_pop, lv_anim_path_overshoot);
    lv_anim_set_exec_cb(&mouth_pop, anim_set_height);
    lv_anim_start(&mouth_pop);

    lv_anim_t eye_pop;
    lv_anim_init(&eye_pop);
    lv_anim_set_values(&eye_pop, FD(12), FD(22));
    lv_anim_set_duration(&eye_pop, 280);
    lv_anim_set_path_cb(&eye_pop, lv_anim_path_overshoot);
    lv_anim_set_exec_cb(&eye_pop, anim_set_height);
    lv_anim_set_var(&eye_pop, s_eye_l);
    lv_anim_start(&eye_pop);
    lv_anim_set_delay(&eye_pop, 50);
    lv_anim_set_var(&eye_pop, s_eye_r);
    lv_anim_start(&eye_pop);

    show_alert_marks(2, true);
}

static void surprise_stage_cb(lv_timer_t *timer)
{
    (void)timer;
    s_surprise_stage_timer = NULL;
    surprise_large();
}

static void surprise_end_cb(lv_timer_t *timer)
{
    (void)timer;
    s_surprise_end_timer = NULL;
    apply_state(s_surprise_return_state);
}

static void surprise_begin(app_state_t return_state)
{
    stop_dynamics();
    s_surprise_return_state = return_state;
    surprise_small();
    s_surprise_stage_timer = lv_timer_create(surprise_stage_cb, 550, NULL);
    lv_timer_set_repeat_count(s_surprise_stage_timer, 1);

    s_surprise_end_timer = lv_timer_create(surprise_end_cb, 2300, NULL);
    lv_timer_set_repeat_count(s_surprise_end_timer, 1);
}

static void expr_neutral(void)
{
    /* Tall capsule eyes (height ~2x width) read as friendly and alert. */
    set_eyes(FD(12), FD(24), -FD(10), col_eye());
    set_mouth(MOUTH_SMILE, col_eye(), FD(3));
    set_texts(NULL, NULL);
}

static void expr_happy(void)
{
    /* squinted, wide "laughing" eyes + bold smile */
    set_eyes(FD(17), FD(9), -FD(10), col_eye());
    set_mouth(MOUTH_SMILE, col_warm(), FD(5));
    set_texts(NULL, NULL);
}

static void expr_sad(const char *symbol, const char *caption)
{
    set_eyes(FD(13), FD(12), -FD(8), col_eye());
    set_mouth(MOUTH_SAD, col_alert(), FD(3));
    set_texts(symbol, caption);
}

static void apply_state(app_state_t state)
{
    /* Any explicit state render cancels an in-flight dizzy overlay. */
    s_current_state = state;
    s_dizzy_active = false;
    if (s_dizzy_end_timer != NULL) {
        lv_timer_delete(s_dizzy_end_timer);
        s_dizzy_end_timer = NULL;
    }

    stop_dynamics();

    switch (state) {
    case APP_STATE_BOOTING:
        set_eyes(FD(14), FD(2), -FD(10), col_eye());
        set_mouth(MOUTH_NONE, col_eye(), 0);
        set_texts(NULL, NULL);
        break;
    case APP_STATE_IDLE:
        expr_neutral();
        s_blink_enabled = true;
        break;
    case APP_STATE_FACE_SCANNING: {
        set_eyes(FD(13), FD(16), -FD(10), col_accent());
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts(NULL, NULL);
        lv_anim_t a;
        lv_anim_init(&a);
        lv_anim_set_values(&a, -FD(5), FD(5));
        lv_anim_set_duration(&a, 700);
        lv_anim_set_playback_duration(&a, 700);
        lv_anim_set_repeat_count(&a, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_path_cb(&a, lv_anim_path_ease_in_out);
        lv_anim_set_exec_cb(&a, anim_translate_x);
        lv_anim_set_var(&a, s_eye_l);
        lv_anim_start(&a);
        lv_anim_set_var(&a, s_eye_r);
        lv_anim_start(&a);
        break;
    }
    case APP_STATE_USER_RECOGNIZED:
        expr_happy();
        break;
    case APP_STATE_UNKNOWN_USER:
        expr_neutral();
        break;
    case APP_STATE_LISTENING:
        set_eyes(FD(14), FD(28), -FD(10), col_accent());
        set_mouth(MOUTH_O, col_eye(), 0);
        set_texts(NULL, NULL);
        break;
    case APP_STATE_THINKING:
        set_eyes(FD(11), FD(18), -FD(14), col_eye());
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts(".", NULL);
        s_think_phase = 0;
        s_think_timer = lv_timer_create(think_timer_cb, 400, NULL);
        break;
    case APP_STATE_SPEAKING:
        set_eyes(FD(14), FD(16), -FD(10), col_eye());
        set_mouth(MOUTH_OPEN, col_warm(), 0);
        set_texts(NULL, NULL);
        break;
    case APP_STATE_CONFUSED:
        set_eyes(FD(12), FD(22), -FD(10), col_eye());
        lv_obj_set_size(s_eye_r, FD(11), FD(11)); /* asymmetric eyes */
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts("?", NULL);
        break;
    case APP_STATE_COMFORT:
        set_eyes(FD(15), FD(8), -FD(9), col_warm());
        set_mouth(MOUTH_SMILE, col_warm(), FD(4));
        set_texts(NULL, NULL);
        break;
    case APP_STATE_PRIVACY_MIC_OFF:
        set_eyes(FD(13), FD(13), -FD(12), col_eye());
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts(LV_SYMBOL_MUTE, NULL);
        break;
    case APP_STATE_PRIVACY_CAMERA_OFF:
        set_eyes(FD(13), FD(13), -FD(12), col_eye());
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts(LV_SYMBOL_EYE_CLOSE, NULL);
        break;
    case APP_STATE_NETWORK_ERROR:
        expr_sad(LV_SYMBOL_WIFI, NULL);
        break;
    case APP_STATE_API_ERROR:
        expr_sad(LV_SYMBOL_WARNING, NULL);
        break;
    case APP_STATE_LOW_POWER:
        set_eyes(FD(14), FD(3), -FD(10), col_eye());
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts(NULL, NULL);
        break;
    default:
        expr_neutral();
        break;
    }

    /* LOW_POWER dims the panel; every other state restores brightness. */
    if (state == APP_STATE_LOW_POWER) {
        bsp_display_brightness_set(15);
        s_dimmed = true;
    } else if (s_dimmed) {
        bsp_display_brightness_set(80);
        s_dimmed = false;
    }
}

/* --- motion interactivity (gaze follow + dizzy) --------------------------- */

/* Motion effects only run in quiet states so they never fight with the
 * conversation, privacy or error expressions. */
static bool motion_allowed(void)
{
    switch (s_current_state) {
    case APP_STATE_IDLE:
    case APP_STATE_UNKNOWN_USER:
    case APP_STATE_USER_RECOGNIZED:
    case APP_STATE_COMFORT:
        return true;
    default:
        return false;
    }
}

static void dizzy_end_cb(lv_timer_t *timer)
{
    (void)timer;
    s_dizzy_end_timer = NULL;
    s_dizzy_active = false;
    apply_state(s_current_state); /* restore the underlying expression */
}

static void dizzy_begin(void)
{
    s_dizzy_active = true;
    stop_dynamics();

    /* 1. Eyes: squeezed almost shut ("ugh...") and drifting slowly. */
    set_eyes(FD(15), FD(4), -FD(8), col_eye());
    lv_anim_t sway_eye;
    lv_anim_init(&sway_eye);
    lv_anim_set_values(&sway_eye, -FD(2), FD(2));
    lv_anim_set_duration(&sway_eye, 420);
    lv_anim_set_playback_duration(&sway_eye, 420);
    lv_anim_set_repeat_count(&sway_eye, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_path_cb(&sway_eye, lv_anim_path_ease_in_out);
    lv_anim_set_exec_cb(&sway_eye, anim_translate_y);
    lv_anim_set_var(&sway_eye, s_eye_l);
    lv_anim_start(&sway_eye);
    lv_anim_set_delay(&sway_eye, 210);
    lv_anim_set_var(&sway_eye, s_eye_r);
    lv_anim_start(&sway_eye);

    /* 2. Whole face sways side to side, like losing balance. */
    lv_anim_t sway_face;
    lv_anim_init(&sway_face);
    lv_anim_set_var(&sway_face, s_face);
    lv_anim_set_values(&sway_face, -FD(3), FD(3));
    lv_anim_set_duration(&sway_face, 480);
    lv_anim_set_playback_duration(&sway_face, 480);
    lv_anim_set_repeat_count(&sway_face, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_path_cb(&sway_face, lv_anim_path_ease_in_out);
    lv_anim_set_exec_cb(&sway_face, anim_translate_x);
    lv_anim_start(&sway_face);

    /* 3. Cartoon sparks orbiting above the head (the classic dizzy halo):
     *    each spark runs an x- and a y-anim 90 degrees out of phase, and
     *    the three sparks are offset by a third of a period. */
    const int32_t orbit_rx = FD(16);
    const int32_t orbit_ry = FD(5);
    const uint32_t half_period = 380;
    for (size_t i = 0; i < 3; i++) {
        if (s_star[i] == NULL) {
            continue;
        }
        face_clear_flag(s_star[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_align(s_star[i], LV_ALIGN_CENTER, 0, -FD(32));

        lv_anim_t ox;
        lv_anim_init(&ox);
        lv_anim_set_var(&ox, s_star[i]);
        lv_anim_set_values(&ox, -orbit_rx, orbit_rx);
        lv_anim_set_duration(&ox, half_period);
        lv_anim_set_playback_duration(&ox, half_period);
        lv_anim_set_repeat_count(&ox, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_delay(&ox, (uint32_t)i * (2 * half_period / 3));
        /* ease-in-out on both axes approximates a sine, so the two
         * out-of-phase animations trace a smooth ellipse. */
        lv_anim_set_path_cb(&ox, lv_anim_path_ease_in_out);
        lv_anim_set_exec_cb(&ox, anim_translate_x);
        lv_anim_start(&ox);

        lv_anim_t oy;
        lv_anim_init(&oy);
        lv_anim_set_var(&oy, s_star[i]);
        lv_anim_set_values(&oy, -orbit_ry, orbit_ry);
        lv_anim_set_duration(&oy, half_period);
        lv_anim_set_playback_duration(&oy, half_period);
        lv_anim_set_repeat_count(&oy, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_delay(&oy, (uint32_t)i * (2 * half_period / 3) + half_period / 2);
        lv_anim_set_path_cb(&oy, lv_anim_path_ease_in_out);
        lv_anim_set_exec_cb(&oy, anim_translate_y);
        lv_anim_start(&oy);
    }

    /* 4. Small wobbly mouth bobbing up and down. */
    set_mouth(MOUTH_O, col_eye(), 0);
    lv_anim_t bob;
    lv_anim_init(&bob);
    lv_anim_set_var(&bob, s_open);
    lv_anim_set_values(&bob, -FD(1), FD(2));
    lv_anim_set_duration(&bob, 300);
    lv_anim_set_playback_duration(&bob, 300);
    lv_anim_set_repeat_count(&bob, LV_ANIM_REPEAT_INFINITE);
    lv_anim_set_path_cb(&bob, lv_anim_path_ease_in_out);
    lv_anim_set_exec_cb(&bob, anim_translate_y);
    lv_anim_start(&bob);

    set_texts(NULL, NULL);

    s_dizzy_end_timer = lv_timer_create(dizzy_end_cb, 2800, NULL);
    lv_timer_set_repeat_count(s_dizzy_end_timer, 1);
}

/* Runs in the LVGL task every 40 ms: consumes the values published by the
 * IMU task. No cross-thread LVGL calls anywhere. */
static void motion_timer_cb(lv_timer_t *timer)
{
    (void)timer;

    if (s_shake_pending) {
        s_shake_pending = false;
        if (motion_allowed() && !s_dizzy_active) {
            dizzy_begin();
        }
    }

    if (s_dizzy_active || !motion_allowed()) {
        return;
    }

    /* Horizontal follow is the dominant, most readable cue; vertical
     * movement is damped so the face keeps eye contact with the user. */
    const int32_t max_x = FD(8);
    const int32_t max_y = FD(5);
    const int32_t dx = (int32_t)((int64_t)s_gaze_x_mil * max_x / 1000);
    const int32_t dy = (int32_t)((int64_t)s_gaze_y_mil * max_y / 1000);
    lv_obj_set_style_translate_x(s_eye_l, dx, 0);
    lv_obj_set_style_translate_x(s_eye_r, dx, 0);
    lv_obj_set_style_translate_y(s_eye_l, dy, 0);
    lv_obj_set_style_translate_y(s_eye_r, dy, 0);
}

void ui_amoled143c_set_gaze(float x, float y)
{
    if (x > 1.0f) { x = 1.0f; } else if (x < -1.0f) { x = -1.0f; }
    if (y > 1.0f) { y = 1.0f; } else if (y < -1.0f) { y = -1.0f; }
    s_gaze_x_mil = (int32_t)(x * 1000.0f);
    s_gaze_y_mil = (int32_t)(y * 1000.0f);
}

void ui_amoled143c_notify_shake(void)
{
    s_shake_pending = true;
}

/* --- face construction --------------------------------------------------- */

static void build_face(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    const int32_t hres = lv_display_get_horizontal_resolution(s_disp);
    const int32_t vres = lv_display_get_vertical_resolution(s_disp);
    s_d = (hres < vres) ? hres : vres;

    s_face = lv_obj_create(screen);
    lv_obj_set_size(s_face, s_d, s_d);
    lv_obj_center(s_face);
    lv_obj_set_style_radius(s_face, LV_RADIUS_CIRCLE, 0);
    /* Deep blue-grey vertical gradient gives the "sphere" some depth while
     * staying near-black for the AMOLED panel. */
    lv_obj_set_style_bg_color(s_face, lv_color_hex(0x18222E), 0);
    lv_obj_set_style_bg_grad_color(s_face, lv_color_hex(0x0A0E13), 0);
    lv_obj_set_style_bg_grad_dir(s_face, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_border_width(s_face, 0, 0);
    lv_obj_set_style_pad_all(s_face, 0, 0);
    face_clear_flag(s_face, LV_OBJ_FLAG_SCROLLABLE);

    s_eye_l = lv_obj_create(s_face);
    s_eye_r = lv_obj_create(s_face);
    lv_obj_t *eyes[] = {s_eye_l, s_eye_r};
    for (size_t i = 0; i < 2; i++) {
        lv_obj_set_style_radius(eyes[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(eyes[i], 0, 0);
        /* Children (the highlight dot) are clipped by the rounded shape,
         * so the highlight vanishes cleanly when the eye blinks shut. */
        lv_obj_set_style_clip_corner(eyes[i], true, 0);
        lv_obj_set_style_pad_all(eyes[i], 0, 0);
        face_clear_flag(eyes[i], LV_OBJ_FLAG_SCROLLABLE);
    }

    /* Catch-light: a soft white dot in the upper-left of each eye. */
    s_hl_l = lv_obj_create(s_eye_l);
    s_hl_r = lv_obj_create(s_eye_r);
    lv_obj_t *hls[] = {s_hl_l, s_hl_r};
    for (size_t i = 0; i < 2; i++) {
        lv_obj_set_size(hls[i], FD(4), FD(4));
        lv_obj_set_style_radius(hls[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(hls[i], 0, 0);
        lv_obj_set_style_bg_color(hls[i], lv_color_white(), 0);
        lv_obj_set_style_bg_opa(hls[i], LV_OPA_70, 0);
        lv_obj_align(hls[i], LV_ALIGN_TOP_LEFT, FD(2), FD(2));
        face_clear_flag(hls[i], LV_OBJ_FLAG_SCROLLABLE);
    }

    s_smile = lv_arc_create(s_face);
    lv_obj_set_size(s_smile, FD(36), FD(36));
    lv_obj_set_style_arc_opa(s_smile, LV_OPA_TRANSP, LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(s_smile, LV_OPA_TRANSP, LV_PART_KNOB);
    lv_obj_set_style_pad_all(s_smile, 0, LV_PART_KNOB);
    lv_obj_set_style_arc_rounded(s_smile, true, LV_PART_MAIN);
    face_clear_flag(s_smile, LV_OBJ_FLAG_CLICKABLE);

    s_flat = lv_obj_create(s_face);
    lv_obj_set_style_radius(s_flat, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_flat, 0, 0);

    s_open = lv_obj_create(s_face);
    lv_obj_set_style_radius(s_open, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_open, 0, 0);
    lv_obj_set_style_pad_all(s_open, 0, 0);
    lv_obj_set_style_clip_corner(s_open, true, 0);

    s_surprise_inner = lv_obj_create(s_open);
    lv_obj_set_style_radius(s_surprise_inner, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_surprise_inner, 0, 0);
    lv_obj_set_style_bg_color(s_surprise_inner, col_coral(), 0);
    lv_obj_set_style_pad_all(s_surprise_inner, 0, 0);
    face_clear_flag(s_surprise_inner, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_surprise_inner, LV_OBJ_FLAG_HIDDEN);

    s_surprise_nose = lv_obj_create(s_face);
    lv_obj_set_style_radius(s_surprise_nose, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(s_surprise_nose, 0, 0);
    lv_obj_set_style_bg_color(s_surprise_nose, col_ink(), 0);
    lv_obj_set_style_pad_all(s_surprise_nose, 0, 0);
    face_clear_flag(s_surprise_nose, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_surprise_nose, LV_OBJ_FLAG_HIDDEN);

    for (size_t i = 0; i < 3; i++) {
        s_alert_bar[i] = lv_obj_create(s_face);
        s_alert_dot[i] = lv_obj_create(s_face);
        lv_obj_t *parts[] = {s_alert_bar[i], s_alert_dot[i]};
        for (size_t j = 0; j < 2; j++) {
            lv_obj_set_style_radius(parts[j], LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_border_width(parts[j], 0, 0);
            lv_obj_set_style_bg_color(parts[j], col_yellow(), 0);
            lv_obj_set_style_pad_all(parts[j], 0, 0);
            face_clear_flag(parts[j], LV_OBJ_FLAG_SCROLLABLE);
            lv_obj_add_flag(parts[j], LV_OBJ_FLAG_HIDDEN);
        }
    }

    /* Dizzy sparks: small pastel dots, hidden until a shake is detected. */
    static const uint32_t star_palette[3] = {0xFFC48A, 0xFFA0B4, 0x7FDBFF};
    for (size_t i = 0; i < 3; i++) {
        s_star[i] = lv_obj_create(s_face);
        lv_obj_set_size(s_star[i], FD(3), FD(3));
        lv_obj_set_style_radius(s_star[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(s_star[i], 0, 0);
        lv_obj_set_style_bg_color(s_star[i], lv_color_hex(star_palette[i]), 0);
        lv_obj_add_flag(s_star[i], LV_OBJ_FLAG_HIDDEN);
    }

    s_status = lv_label_create(s_face);
#if LV_FONT_MONTSERRAT_24
    lv_obj_set_style_text_font(s_status, &lv_font_montserrat_24, 0);
#endif
    lv_obj_set_style_text_color(s_status, col_accent(), 0);
    lv_obj_align(s_status, LV_ALIGN_CENTER, 0, FD(34));

    s_caption = lv_label_create(s_face);
#if LV_FONT_SOURCE_HAN_SANS_SC_16_CJK
    lv_obj_set_style_text_font(s_caption, &lv_font_source_han_sans_sc_16_cjk, 0);
#endif
    lv_obj_set_style_text_color(s_caption, col_eye(), 0);
    lv_obj_set_width(s_caption, FD(70));
    lv_obj_set_style_text_align(s_caption, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_caption, LV_ALIGN_CENTER, 0, FD(34));

    s_blink_timer = lv_timer_create(blink_timer_cb, 3500, NULL);
    s_motion_timer = lv_timer_create(motion_timer_cb, 40, NULL);

    apply_state(APP_STATE_BOOTING);
}

/* --- ui_board strong implementations ------------------------------------- */

esp_err_t ui_board_init(void)
{
    s_disp = bsp_display_start();
    if (s_disp == NULL) {
        ESP_LOGE(TAG, "bsp_display_start failed");
        return ESP_FAIL;
    }
    bsp_display_brightness_set(80);

    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    build_face();
    bsp_display_unlock();

    ESP_LOGI(TAG, "AMOLED 1.43C round face UI ready, canvas d=%d px", (int)s_d);
    return ESP_OK;
}

esp_err_t ui_board_show_state(app_state_t state)
{
    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    apply_state(state);
    bsp_display_unlock();
    return ESP_OK;
}

esp_err_t ui_board_play_boot_animation(void)
{
    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    apply_state(APP_STATE_BOOTING);
    surprise_begin(APP_STATE_IDLE);
    bsp_display_unlock();
    return ESP_OK;
}

esp_err_t ui_board_show_face(const char *emotion, float intensity)
{
    if (emotion == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (intensity < 0.0f) {
        intensity = 0.0f;
    } else if (intensity > 1.0f) {
        intensity = 1.0f;
    }
    const int32_t weight = FD(2) + (int32_t)(intensity * (float)FD(3));

    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    stop_dynamics();
    if (strcmp(emotion, "smile") == 0 || strcmp(emotion, "happy") == 0) {
        set_eyes(FD(16), FD(10), -FD(10), col_eye());
        set_mouth(MOUTH_SMILE, col_warm(), weight);
        set_texts(NULL, NULL);
    } else if (strcmp(emotion, "sad") == 0) {
        expr_sad(NULL, NULL);
    } else if (strcmp(emotion, "surprised") == 0) {
        surprise_begin(s_current_state);
    } else if (strcmp(emotion, "confused") == 0) {
        set_eyes(FD(14), FD(18), -FD(10), col_eye());
        lv_obj_set_size(s_eye_r, FD(11), FD(11));
        set_mouth(MOUTH_FLAT, col_eye(), FD(2));
        set_texts("?", NULL);
    } else if (strcmp(emotion, "comfort") == 0 || strcmp(emotion, "gentle") == 0) {
        set_eyes(FD(15), FD(8), -FD(9), col_warm());
        set_mouth(MOUTH_SMILE, col_warm(), weight);
        set_texts(NULL, NULL);
    } else {
        /* unknown emotion string: neutral face, report unsupported so the
         * facade also logs it for diagnosis. */
        expr_neutral();
        bsp_display_unlock();
        return ESP_ERR_NOT_SUPPORTED;
    }
    bsp_display_unlock();
    return ESP_OK;
}

esp_err_t ui_board_show_user(bool recognized, const char *display_name)
{
    if (display_name == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    stop_dynamics();
    if (recognized) {
        expr_happy();
    } else {
        expr_neutral();
    }
    /* lv_label_set_text copies the borrowed string. */
    set_texts(NULL, display_name);
    bsp_display_unlock();
    return ESP_OK;
}

esp_err_t ui_board_show_error(const char *code, const char *message)
{
    if (code == NULL || message == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const char *symbol = LV_SYMBOL_WARNING;
    if (strcmp(code, "NETWORK_ERROR") == 0) {
        symbol = LV_SYMBOL_WIFI;
    }
    if (!bsp_display_lock(1000)) {
        return ESP_ERR_TIMEOUT;
    }
    stop_dynamics();
    expr_sad(symbol, message);
    lv_obj_align(s_status, LV_ALIGN_CENTER, 0, FD(34));
    lv_obj_align(s_caption, LV_ALIGN_CENTER, 0, FD(44));
    bsp_display_unlock();
    return ESP_OK;
}

esp_err_t ui_board_set_brightness(uint8_t percent)
{
    s_dimmed = false;
    return bsp_display_brightness_set(percent);
}

/* Audio stays a mock until Phase 6; the facade keeps its log fallback. */
esp_err_t ui_board_play_sound(const char *name)
{
    (void)name;
    return ESP_ERR_NOT_SUPPORTED;
}

#endif /* CONFIG_ELDER_UI_BOARD_AMOLED143C */
