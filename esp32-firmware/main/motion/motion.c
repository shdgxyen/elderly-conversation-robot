/*
 * QMI8658 IMU sampling for face interactivity.
 *
 * - Gaze: the accelerometer senses the gravity vector; tilting the board
 *   makes the eyes look "downhill" (low-pass filtered).
 * - Dizzy: sustained high gyroscope magnitude (the robot being shaken)
 *   triggers a short dizzy animation in the face adapter.
 *
 * The sensor task never touches LVGL. It publishes values through the
 * thread-safe hooks in ui_board_amoled18.h; an LVGL-side timer consumes
 * them. This keeps sensor code and UI code fully decoupled.
 */

#include "sdkconfig.h"

#if CONFIG_ELDER_UI_MOTION

#include <math.h>
#include <stdbool.h>
#include <stdint.h>

#include "esp_check.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "bsp/esp-bsp.h"
#include "driver/i2c_master.h"
#include "qmi8658.h"

#include "motion.h"
#include "ui_board_amoled18.h"

static const char *TAG = "motion";

#define MOTION_SAMPLE_PERIOD_MS 50   /* 20 Hz */
#define MOTION_TASK_STACK 3072
#define MOTION_TASK_PRIORITY 5

/* Tilt mapping: ~20 degrees of tilt = full gaze deflection, so the effect
 * is clearly visible with a gentle tilt. If the eyes move the wrong way on
 * the real board, flip the sign constants. */
#define GAZE_FULL_SCALE_MPS2 3.4f
#define GAZE_SIGN_X (+1.0f)
#define GAZE_SIGN_Y (+1.0f)
#define GAZE_LOWPASS_ALPHA 0.35f

/* Shake detection. Requirements learned from real-device testing:
 * casual handling must NOT trigger dizzy. So we demand vigorous rotation
 * (high dps) sustained for ~0.4 s, followed by a cooldown. */
#define SHAKE_THRESHOLD_DPS 450.0f
#define SHAKE_SAMPLES_REQUIRED 8   /* 8 x 50 ms = 0.4 s of hard shaking */
#define SHAKE_COOLDOWN_MS 3000

static qmi8658_dev_t s_imu;

static float clampf(float value, float lo, float hi)
{
    if (value < lo) {
        return lo;
    }
    if (value > hi) {
        return hi;
    }
    return value;
}

static void motion_task(void *arg)
{
    (void)arg;
    float gaze_x = 0.0f;
    float gaze_y = 0.0f;
    int shake_streak = 0;
    TickType_t cooldown_until = 0;

    while (true) {
        qmi8658_data_t data = {0};
        if (qmi8658_read_sensor_data(&s_imu, &data) == ESP_OK) {
            /* --- gaze from gravity tilt ------------------------------- */
            const float tx = clampf(GAZE_SIGN_X * data.accelX / GAZE_FULL_SCALE_MPS2,
                                    -1.0f, 1.0f);
            const float ty = clampf(GAZE_SIGN_Y * data.accelY / GAZE_FULL_SCALE_MPS2,
                                    -1.0f, 1.0f);
            gaze_x += GAZE_LOWPASS_ALPHA * (tx - gaze_x);
            gaze_y += GAZE_LOWPASS_ALPHA * (ty - gaze_y);
            ui_amoled18_set_gaze(gaze_x, gaze_y);

            /* --- shake detection from gyro magnitude ------------------ */
            const float mag = sqrtf(data.gyroX * data.gyroX +
                                    data.gyroY * data.gyroY +
                                    data.gyroZ * data.gyroZ);
            if (mag > SHAKE_THRESHOLD_DPS) {
                shake_streak++;
            } else {
                shake_streak = 0;
            }

            const TickType_t now = xTaskGetTickCount();
            if (shake_streak >= SHAKE_SAMPLES_REQUIRED && now >= cooldown_until) {
                cooldown_until = now + pdMS_TO_TICKS(SHAKE_COOLDOWN_MS);
                shake_streak = 0;
                ESP_LOGI(TAG, "shake detected (%.0f dps)", (double)mag);
                ui_amoled18_notify_shake();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(MOTION_SAMPLE_PERIOD_MS));
    }
}

esp_err_t motion_start(void)
{
    /* Reuse the board's shared I2C bus (touch + PMU + IMU live together).
     * bsp_i2c_init() is idempotent: it returns OK when already set up. */
    esp_err_t ret = bsp_i2c_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "shared I2C init failed: %s", esp_err_to_name(ret));
        return ret;
    }
    i2c_master_bus_handle_t bus = bsp_i2c_get_handle();
    if (bus == NULL) {
        return ESP_ERR_INVALID_STATE;
    }

    uint8_t address = 0;
    const uint8_t candidates[] = {QMI8658_ADDRESS_HIGH, QMI8658_ADDRESS_LOW};
    for (size_t i = 0; i < sizeof(candidates); i++) {
        if (i2c_master_probe(bus, candidates[i], 100) == ESP_OK) {
            address = candidates[i];
            break;
        }
    }
    if (address == 0) {
        ESP_LOGW(TAG, "QMI8658 not found; motion features disabled");
        return ESP_ERR_NOT_FOUND;
    }

    ret = qmi8658_init(&s_imu, bus, address);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "QMI8658 init failed: %s", esp_err_to_name(ret));
        return ret;
    }

    /* Same configuration as the vendor example 92_qmi8658_imu. */
    ESP_RETURN_ON_ERROR(qmi8658_set_accel_range(&s_imu, QMI8658_ACCEL_RANGE_4G), TAG, "accel range");
    ESP_RETURN_ON_ERROR(qmi8658_set_accel_odr(&s_imu, QMI8658_ACCEL_ODR_250HZ), TAG, "accel odr");
    /* Wide gyro range so hard shakes don't clip below the dizzy threshold. */
    ESP_RETURN_ON_ERROR(qmi8658_set_gyro_range(&s_imu, QMI8658_GYRO_RANGE_1024DPS), TAG, "gyro range");
    ESP_RETURN_ON_ERROR(qmi8658_set_gyro_odr(&s_imu, QMI8658_GYRO_ODR_250HZ), TAG, "gyro odr");
    qmi8658_set_accel_unit_mps2(&s_imu, true);
    qmi8658_set_gyro_unit_dps(&s_imu, true);
    ESP_RETURN_ON_ERROR(qmi8658_enable_sensors(&s_imu, QMI8658_ENABLE_ACCEL | QMI8658_ENABLE_GYRO),
                        TAG, "enable sensors");

    if (xTaskCreate(motion_task, "motion", MOTION_TASK_STACK, NULL,
                    MOTION_TASK_PRIORITY, NULL) != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "IMU motion task started (QMI8658 at 0x%02x)", address);
    return ESP_OK;
}

#endif /* CONFIG_ELDER_UI_MOTION */
