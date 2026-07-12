/*
 * Strong ui_board_* implementation for the Waveshare ESP32-S3-Touch-AMOLED-1.8
 * (368x448, SH8601). Rendering is done with LVGL 9 through the official
 * managed BSP component, which owns the panel/touch initialization and pins.
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

#if CONFIG_ELDER_UI_BOARD_AMOLED18

#include <string.h>

#include "esp_err.h"
#include "esp_log.h"

#include "bsp/esp-bsp.h"
#include "lvgl.h"

#include "app_state.h"
#include "ui_board.h"

static const char *TAG = "ui_amoled18";

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

static lv_timer_t *s_blink_timer;
static lv_timer_t *s_think_timer;
static bool s_blink_enabled;
static int s_think_phase;
static bool s_dimmed;

static int32_t s_eye_w, s_eye_h; /* current nominal eye size */

typedef enum {
    MOUTH_SMILE,
    MOUTH_SAD,
    MOUTH_FLAT,
    MOUTH_O,     /* small round mouth */
    MOUTH_OPEN,  /* animated talking mouth */
    MOUTH_NONE,
} mouth_mode_t;

/* --- small helpers (LVGL task or under bsp_display_lock) ---------------- */

static void anim_set_height(void *obj, int32_t v)
{
    lv_obj_set_height((lv_obj_t *)obj, v);
}

static void anim_translate_x(void *obj, int32_t v)
{
    lv_obj_set_style_translate_x((lv_obj_t *)obj, v, 0);
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
    lv_anim_delete(s_eye_l, NULL);
    lv_anim_delete(s_eye_r, NULL);
    lv_anim_delete(s_open, NULL);
    lv_obj_set_style_translate_x(s_eye_l, 0, 0);
    lv_obj_set_style_translate_x(s_eye_r, 0, 0);
}

static void set_eyes(int32_t w, int32_t h, int32_t dy, lv_color_t color)
{
    s_eye_w = w;
    s_eye_h = h;
    lv_obj_set_size(s_eye_l, w, h);
    lv_obj_set_size(s_eye_r, w, h);
    lv_obj_align(s_eye_l, LV_ALIGN_CENTER, -FD(22), dy);
    lv_obj_align(s_eye_r, LV_ALIGN_CENTER, FD(22), dy);
    lv_obj_set_style_bg_color(s_eye_l, color, 0);
    lv_obj_set_style_bg_color(s_eye_r, color, 0);
}

static void set_mouth(mouth_mode_t mode, lv_color_t color, int32_t weight)
{
    lv_obj_add_flag(s_smile, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_flat, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_open, LV_OBJ_FLAG_HIDDEN);

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

/* --- expression presets -------------------------------------------------- */

static void expr_neutral(void)
{
    set_eyes(FD(14), FD(18), -FD(10), col_eye());
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
        set_eyes(FD(16), FD(22), -FD(10), col_accent());
        set_mouth(MOUTH_O, col_eye(), 0);
        set_texts(NULL, NULL);
        break;
    case APP_STATE_THINKING:
        set_eyes(FD(13), FD(15), -FD(14), col_eye());
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
        set_eyes(FD(14), FD(18), -FD(10), col_eye());
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
    lv_obj_set_style_bg_color(s_face, lv_color_hex(0x101418), 0);
    lv_obj_set_style_border_width(s_face, 0, 0);
    lv_obj_set_style_pad_all(s_face, 0, 0);
    face_clear_flag(s_face, LV_OBJ_FLAG_SCROLLABLE);

    s_eye_l = lv_obj_create(s_face);
    s_eye_r = lv_obj_create(s_face);
    lv_obj_t *eyes[] = {s_eye_l, s_eye_r};
    for (size_t i = 0; i < 2; i++) {
        lv_obj_set_style_radius(eyes[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_border_width(eyes[i], 0, 0);
        face_clear_flag(eyes[i], LV_OBJ_FLAG_SCROLLABLE);
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

    s_status = lv_label_create(s_face);
#if LV_FONT_MONTSERRAT_24
    lv_obj_set_style_text_font(s_status, &lv_font_montserrat_24, 0);
#endif
    lv_obj_set_style_text_color(s_status, col_accent(), 0);
    lv_obj_align(s_status, LV_ALIGN_CENTER, 0, FD(34));

    s_caption = lv_label_create(s_face);
#if LV_FONT_SIMSUN_16_CJK
    lv_obj_set_style_text_font(s_caption, &lv_font_simsun_16_cjk, 0);
#endif
    lv_obj_set_style_text_color(s_caption, col_eye(), 0);
    lv_obj_set_width(s_caption, FD(70));
    lv_obj_set_style_text_align(s_caption, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_caption, LV_ALIGN_CENTER, 0, FD(34));

    s_blink_timer = lv_timer_create(blink_timer_cb, 3500, NULL);

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

    ESP_LOGI(TAG, "AMOLED 1.8 face UI ready, canvas d=%d px", (int)s_d);
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
    /* eyes open slowly, then a smile appears */
    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_values(&a, FD(2), FD(18));
    lv_anim_set_duration(&a, 600);
    lv_anim_set_exec_cb(&a, anim_set_height);
    lv_anim_set_var(&a, s_eye_l);
    lv_anim_start(&a);
    lv_anim_set_var(&a, s_eye_r);
    lv_anim_set_delay(&a, 120);
    lv_anim_start(&a);
    set_mouth(MOUTH_SMILE, col_eye(), FD(3));
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
        set_eyes(FD(17), FD(22), -FD(10), col_eye());
        set_mouth(MOUTH_O, col_eye(), 0);
        set_texts(NULL, NULL);
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

#endif /* CONFIG_ELDER_UI_BOARD_AMOLED18 */
