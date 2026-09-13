#include "protocol.h"

#include <ctype.h>
#include <math.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "sdkconfig.h"
#include "cJSON.h"

#include "app_state.h"
#include "audio_loopback.h"
#include "ui.h"
#include "usb_serial.h"

enum {
    TYPE_MAX_BYTES = 24,
    STATE_MAX_BYTES = 32,
    EMOTION_MAX_BYTES = 256,
    DISPLAY_NAME_MAX_BYTES = 512,
    ERROR_CODE_MAX_BYTES = 256,
    ERROR_MESSAGE_MAX_BYTES = CONFIG_ELDER_JSON_LINE_MAX_LENGTH,
    SOUND_NAME_MAX_BYTES = 256,
    EVENT_NAME_MAX_BYTES = 48,
};

static bool bytes_are_valid_utf8(const char *value, size_t length)
{
    const unsigned char *bytes = (const unsigned char *)value;
    size_t i = 0;

    while (i < length) {
        const unsigned char first = bytes[i];
        if (first <= 0x7F) {
            ++i;
            continue;
        }

        if (first >= 0xC2 && first <= 0xDF) {
            if (i + 1 >= length || bytes[i + 1] < 0x80 || bytes[i + 1] > 0xBF) {
                return false;
            }
            i += 2;
            continue;
        }

        if (first >= 0xE0 && first <= 0xEF) {
            if (i + 2 >= length ||
                bytes[i + 2] < 0x80 || bytes[i + 2] > 0xBF) {
                return false;
            }
            const unsigned char second = bytes[i + 1];
            if ((first == 0xE0 && (second < 0xA0 || second > 0xBF)) ||
                (first == 0xED && (second < 0x80 || second > 0x9F)) ||
                ((first != 0xE0 && first != 0xED) &&
                 (second < 0x80 || second > 0xBF))) {
                return false;
            }
            i += 3;
            continue;
        }

        if (first >= 0xF0 && first <= 0xF4) {
            if (i + 3 >= length ||
                bytes[i + 2] < 0x80 || bytes[i + 2] > 0xBF ||
                bytes[i + 3] < 0x80 || bytes[i + 3] > 0xBF) {
                return false;
            }
            const unsigned char second = bytes[i + 1];
            if ((first == 0xF0 && (second < 0x90 || second > 0xBF)) ||
                (first == 0xF4 && (second < 0x80 || second > 0x8F)) ||
                ((first != 0xF0 && first != 0xF4) &&
                 (second < 0x80 || second > 0xBF))) {
                return false;
            }
            i += 4;
            continue;
        }

        return false;
    }
    return true;
}

static bool object_has_unique_keys(const cJSON *root)
{
    for (const cJSON *item = root->child; item != NULL; item = item->next) {
        if (item->string == NULL) {
            return false;
        }
        for (const cJSON *other = item->next; other != NULL; other = other->next) {
            if (other->string == NULL || strcmp(item->string, other->string) == 0) {
                return false;
            }
        }
    }
    return true;
}

static bool object_has_only_fields(const cJSON *root,
                                   const char *const *allowed_fields,
                                   size_t allowed_count)
{
    for (const cJSON *item = root->child; item != NULL; item = item->next) {
        bool allowed = false;
        for (size_t i = 0; i < allowed_count; ++i) {
            if (strcmp(item->string, allowed_fields[i]) == 0) {
                allowed = true;
                break;
            }
        }
        if (!allowed) {
            return false;
        }
    }
    return true;
}

static bool fields_are_valid_for_type(const cJSON *root, const char *type)
{
    static const char *const state_fields[] = {"type", "state"};
    static const char *const face_fields[] = {"type", "emotion", "intensity"};
    static const char *const user_fields[] = {"type", "recognized", "display_name"};
    static const char *const error_fields[] = {"type", "code", "message"};
    static const char *const display_fields[] = {"type", "brightness"};
    static const char *const sound_fields[] = {"type", "name"};

#define FIELDS_MATCH(field_array) \
    object_has_only_fields(root, field_array, sizeof(field_array) / sizeof(field_array[0]))

    if (strcmp(type, "state") == 0) {
        return FIELDS_MATCH(state_fields);
    }
    if (strcmp(type, "face") == 0) {
        return FIELDS_MATCH(face_fields);
    }
    if (strcmp(type, "user") == 0) {
        return FIELDS_MATCH(user_fields);
    }
    if (strcmp(type, "error") == 0) {
        return FIELDS_MATCH(error_fields);
    }
    if (strcmp(type, "display") == 0) {
        return FIELDS_MATCH(display_fields);
    }
    if (strcmp(type, "sound") == 0) {
        return FIELDS_MATCH(sound_fields);
    }

#undef FIELDS_MATCH
    return true;
}

static bool json_string_is_bounded(const cJSON *item,
                                   size_t maximum_length,
                                   bool allow_empty)
{
    if (!cJSON_IsString(item) || item->valuestring == NULL) {
        return false;
    }
    const size_t length = strnlen(item->valuestring, maximum_length + 1);
    if (length > maximum_length || (length == 0 && !allow_empty)) {
        return false;
    }
    if (allow_empty) {
        return true;
    }
    for (size_t i = 0; i < length; ++i) {
        if (!isspace((unsigned char)item->valuestring[i])) {
            return true;
        }
    }
    return false;
}

static protocol_result_t action_result(esp_err_t result)
{
    return result == ESP_OK ? PROTOCOL_RESULT_OK : PROTOCOL_RESULT_ACTION_FAILED;
}

static protocol_result_t handle_state(const cJSON *root)
{
    const cJSON *state_item = cJSON_GetObjectItemCaseSensitive(root, "state");
    if (!json_string_is_bounded(state_item, STATE_MAX_BYTES, false)) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    app_state_t state;
    if (!app_state_from_string(state_item->valuestring, &state)) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }
    return action_result(app_state_set(state));
}

static protocol_result_t handle_face(const cJSON *root)
{
    const cJSON *emotion = cJSON_GetObjectItemCaseSensitive(root, "emotion");
    const cJSON *intensity = cJSON_GetObjectItemCaseSensitive(root, "intensity");
    if (!json_string_is_bounded(emotion, EMOTION_MAX_BYTES, false) ||
        !cJSON_IsNumber(intensity) ||
        !isfinite(intensity->valuedouble) ||
        intensity->valuedouble < 0.0 ||
        intensity->valuedouble > 1.0) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    return action_result(ui_show_face(emotion->valuestring,
                                      (float)intensity->valuedouble));
}

static protocol_result_t handle_user(const cJSON *root)
{
    const cJSON *recognized = cJSON_GetObjectItemCaseSensitive(root, "recognized");
    const cJSON *display_name = cJSON_GetObjectItemCaseSensitive(root, "display_name");
    if (!cJSON_IsBool(recognized)) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    const bool is_recognized = cJSON_IsTrue(recognized);
    const char *name = NULL;
    if (is_recognized) {
        if (!json_string_is_bounded(display_name, DISPLAY_NAME_MAX_BYTES, false)) {
            return PROTOCOL_RESULT_INVALID_MESSAGE;
        }
        name = display_name->valuestring;
    } else if (display_name == NULL) {
        name = "访客";
    } else {
        if (!json_string_is_bounded(display_name, DISPLAY_NAME_MAX_BYTES, false)) {
            return PROTOCOL_RESULT_INVALID_MESSAGE;
        }
        name = display_name->valuestring;
    }

    esp_err_t result = app_state_set(is_recognized ? APP_STATE_USER_RECOGNIZED
                                                    : APP_STATE_UNKNOWN_USER);
    if (result == ESP_OK) {
        /* Render the name after the state face so the overlay remains visible. */
        result = ui_show_user(is_recognized, name);
    }
    return action_result(result);
}

static protocol_result_t handle_error(const cJSON *root)
{
    const cJSON *code = cJSON_GetObjectItemCaseSensitive(root, "code");
    const cJSON *message = cJSON_GetObjectItemCaseSensitive(root, "message");
    if (!json_string_is_bounded(code, ERROR_CODE_MAX_BYTES, false) ||
        !json_string_is_bounded(message, ERROR_MESSAGE_MAX_BYTES, false)) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    esp_err_t result = ESP_OK;
    if (strcmp(code->valuestring, "NETWORK_ERROR") == 0) {
        result = app_state_set(APP_STATE_NETWORK_ERROR);
    } else if (strcmp(code->valuestring, "API_ERROR") == 0) {
        result = app_state_set(APP_STATE_API_ERROR);
    }
    if (result == ESP_OK) {
        /* Draw details after the error face so the message is not overwritten. */
        result = ui_show_error(code->valuestring, message->valuestring);
    }
    return action_result(result);
}

static protocol_result_t handle_display(const cJSON *root)
{
    const cJSON *brightness = cJSON_GetObjectItemCaseSensitive(root, "brightness");
    if (!cJSON_IsNumber(brightness) ||
        !isfinite(brightness->valuedouble) ||
        brightness->valuedouble < 0.0 ||
        brightness->valuedouble > 100.0 ||
        floor(brightness->valuedouble) != brightness->valuedouble) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }
    return action_result(ui_set_brightness((uint8_t)brightness->valuedouble));
}

static protocol_result_t handle_sound(const cJSON *root)
{
    const cJSON *name = cJSON_GetObjectItemCaseSensitive(root, "name");
    if (!json_string_is_bounded(name, SOUND_NAME_MAX_BYTES, false)) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }
#if CONFIG_ELDER_AUDIO_LOOPBACK_TEST
    /* The only real sound so far is the built-in speaker test clip. */
    if (strcmp(name->valuestring, "speaker_test") == 0) {
        return action_result(audio_loopback_request_speaker_test());
    }
#endif
    return action_result(ui_play_sound(name->valuestring));
}

protocol_result_t protocol_handle_line(const char *line, size_t length)
{
    if (line == NULL || length == 0) {
        return PROTOCOL_RESULT_INVALID_ARGUMENT;
    }
    if (length > CONFIG_ELDER_JSON_LINE_MAX_LENGTH) {
        return PROTOCOL_RESULT_LINE_TOO_LONG;
    }
    if (memchr(line, '\0', length) != NULL) {
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }
    if (!bytes_are_valid_utf8(line, length)) {
        return PROTOCOL_RESULT_INVALID_JSON;
    }

    char *terminated_line = malloc(length + 1);
    if (terminated_line == NULL) {
        return PROTOCOL_RESULT_ACTION_FAILED;
    }
    memcpy(terminated_line, line, length);
    terminated_line[length] = '\0';

    cJSON *root = cJSON_ParseWithLengthOpts(terminated_line,
                                            length + 1,
                                            NULL,
                                            true);
    free(terminated_line);
    if (root == NULL) {
        return PROTOCOL_RESULT_INVALID_JSON;
    }
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }
    if (!object_has_unique_keys(root)) {
        cJSON_Delete(root);
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    protocol_result_t result = PROTOCOL_RESULT_INVALID_MESSAGE;
    if (!json_string_is_bounded(type, TYPE_MAX_BYTES, false)) {
        cJSON_Delete(root);
        return result;
    }
    if (!fields_are_valid_for_type(root, type->valuestring)) {
        cJSON_Delete(root);
        return PROTOCOL_RESULT_INVALID_MESSAGE;
    }

    if (strcmp(type->valuestring, "state") == 0) {
        result = handle_state(root);
    } else if (strcmp(type->valuestring, "face") == 0) {
        result = handle_face(root);
    } else if (strcmp(type->valuestring, "user") == 0) {
        result = handle_user(root);
    } else if (strcmp(type->valuestring, "error") == 0) {
        result = handle_error(root);
    } else if (strcmp(type->valuestring, "display") == 0) {
        result = handle_display(root);
    } else if (strcmp(type->valuestring, "sound") == 0) {
        result = handle_sound(root);
    } else {
        result = PROTOCOL_RESULT_UNSUPPORTED_TYPE;
    }

    cJSON_Delete(root);
    return result;
}

const char *protocol_result_to_string(protocol_result_t result)
{
    switch (result) {
    case PROTOCOL_RESULT_OK:
        return "ok";
    case PROTOCOL_RESULT_INVALID_ARGUMENT:
        return "invalid_argument";
    case PROTOCOL_RESULT_LINE_TOO_LONG:
        return "line_too_long";
    case PROTOCOL_RESULT_INVALID_JSON:
        return "invalid_json";
    case PROTOCOL_RESULT_INVALID_MESSAGE:
        return "invalid_message";
    case PROTOCOL_RESULT_UNSUPPORTED_TYPE:
        return "unsupported_type";
    case PROTOCOL_RESULT_ACTION_FAILED:
        return "action_failed";
    default:
        return "unknown_result";
    }
}

static esp_err_t send_json_object(cJSON *root)
{
    if (root == NULL) {
        return ESP_ERR_NO_MEM;
    }

    char *encoded = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (encoded == NULL) {
        return ESP_ERR_NO_MEM;
    }

    const size_t length = strlen(encoded);
    const esp_err_t result = usb_serial_send_line(encoded, length);
    cJSON_free(encoded);
    return result;
}

esp_err_t protocol_send_button_event(const char *event_name)
{
    if (event_name == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const size_t length = strnlen(event_name, EVENT_NAME_MAX_BYTES + 1);
    if (length == 0 || length > EVENT_NAME_MAX_BYTES) {
        return ESP_ERR_INVALID_ARG;
    }

    cJSON *root = cJSON_CreateObject();
    if (root == NULL) {
        return ESP_ERR_NO_MEM;
    }
    if (cJSON_AddStringToObject(root, "type", "event") == NULL ||
        cJSON_AddStringToObject(root, "event", event_name) == NULL) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    return send_json_object(root);
}

esp_err_t protocol_send_heartbeat(uint64_t uptime_ms)
{
    cJSON *root = cJSON_CreateObject();
    if (root == NULL) {
        return ESP_ERR_NO_MEM;
    }
    if (cJSON_AddStringToObject(root, "type", "heartbeat") == NULL ||
        cJSON_AddNumberToObject(root, "uptime_ms", (double)uptime_ms) == NULL) {
        cJSON_Delete(root);
        return ESP_ERR_NO_MEM;
    }
    return send_json_object(root);
}
