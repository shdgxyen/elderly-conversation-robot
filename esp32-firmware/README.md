# ESP32-S3 firmware (Phase 0 / Phase 2)

This directory contains the ESP-IDF skeleton for the round-screen terminal in
`docs/PROJECT_SPEC.md`. Its current responsibility is deliberately small:

- maintain every specified device state;
- receive bounded JSON Lines commands from the Raspberry Pi;
- expose state, face, user, error, brightness, and prompt-sound UI actions;
- report periodic heartbeats and debounced WAKE/STOP events;
- provide a clean UI hardware-adapter boundary for the Waveshare BSP.

The real microphone, speaker, touch controller, face camera, and full LVGL
graphics/audio path are outside this phase. `sound` is a visible/log mock.

## Recommended toolchain

Use the vendor demo as the integration baseline:

- [Waveshare ESP32-S3-Touch-AMOLED-1.43C documentation](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.43C)
- [Waveshare official demo repository](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.43C), currently containing an `espidf_v5.5.3` example
- ESP-IDF 5.5.x, preferably 5.5.3 to match that demo

The current official LVGL 9 BSP port declares ESP-IDF `>=5.5`, LVGL `^9.4.0`
(the demo currently uses 9.5.0), `esp_lvgl_adapter ^0.4.1`, and
`esp_lcd_sh8601 ^2.0.1`. Those managed components are intentionally **not**
added yet: this phase must remain buildable without copying vendor code or
assuming its license/integration choices.

The documented module is ESP32-S3-PICO-1-N8R8 with a 466 x 466 CO5300 AMOLED
and CST820 touch controller. The official board configuration identifies its
on-board BOOT key as GPIO0 and LED as GPIO5. These facts are recorded only to
guide the later BSP integration. This project does not repurpose either pin or
guess GPIOs for the product's external WAKE and STOP controls.

## Build and flash

Install/activate ESP-IDF first, then run:

```bash
cd esp32-firmware
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM0 flash
idf.py -p /dev/ttyACM0 monitor
```

Replace the port with the one present on the build machine. The top-level
CMake file also defaults a fresh build to `esp32s3` when no target was supplied.

ESP-IDF tooling can fail on some installations when a source/build path has
non-ASCII characters or spaces. This repository currently lives below a path
containing Chinese characters. If CMake, Ninja, or an ESP-IDF Python tool shows
an unexplained path/encoding error, copy or check out `esp32-firmware` into an
ASCII-only path without spaces and build there.

## Transport selection

`Component config -> Elder companion firmware -> JSON Lines transport` offers:

1. **ESP32-S3 USB Serial/JTAG** (default): uses the native USB Serial/JTAG
   peripheral for protocol traffic.
2. **Hardware UART**: requires an explicit controller/routing choice. TX/RX
   default to `-1` (`UART_PIN_NO_CHANGE`) so the skeleton never invents board
   pins. Set real pins after the wiring/BSP is confirmed.

`sdkconfig.defaults` keeps ESP-IDF logs on UART0 while the default JSON protocol
uses USB Serial/JTAG. Keep logs and protocol on different channels. If UART is
selected for JSON Lines, move/disable the ESP-IDF console as appropriate; log
text on the same wire is not valid JSON Lines.

Each incoming JSON payload is capped by
`CONFIG_ELDER_JSON_LINE_MAX_LENGTH` (2048 bytes by default); the terminating LF
is not included in that limit. An oversized line is discarded up to the next
LF. Outgoing writes are mutex-protected so heartbeat and button tasks cannot
interleave.

## Protocol

Raspberry Pi to ESP32 examples:

```json
{"type":"state","state":"LISTENING"}
{"type":"face","emotion":"smile","intensity":0.8}
{"type":"user","recognized":true,"display_name":"张奶奶"}
{"type":"error","code":"NETWORK_ERROR","message":"网络连接失败"}
{"type":"display","brightness":70}
{"type":"sound","name":"wake"}
```

The accepted state values are:

```text
BOOTING IDLE FACE_SCANNING USER_RECOGNIZED UNKNOWN_USER LISTENING THINKING
SPEAKING CONFUSED COMFORT PRIVACY_MIC_OFF PRIVACY_CAMERA_OFF NETWORK_ERROR
API_ERROR LOW_POWER
```

ESP32 to Raspberry Pi examples:

```json
{"type":"event","event":"WAKE_BUTTON_PRESSED"}
{"type":"event","event":"STOP_BUTTON_PRESSED"}
{"type":"heartbeat","uptime_ms":123456}
```

Messages are unacknowledged in Phase 2. Known command objects are strict:
duplicate keys and fields outside that command's schema are rejected. Invalid
JSON/UTF-8, unknown types, invalid states, out-of-range intensity/brightness,
embedded NULs, blank required strings, and overlong strings are also rejected
without changing device state. For `recognized:false`, `display_name` may be
omitted and the UI uses `访客`. Every cJSON tree/encoded buffer is released on
its completion path.

String limits in the C decoder are wire-byte limits (not Unicode code-point
counts): emotion/error code/sound name 256 bytes, display name 512 bytes, and
error message up to the 2048-byte payload ceiling. The complete encoded JSON
payload, including its keys and other fields, must still fit that 2048-byte
line limit.

## Buttons

Both external buttons are disabled by default. Enable them independently under
`Component config -> Elder companion firmware -> External buttons`, then enter
the confirmed GPIO number and polarity. A configured `-1` pin is rejected at
startup. Inputs are polled and debounced in a FreeRTOS task; callbacks run only
on a stable press, not continuously while held.

## UI / Waveshare BSP integration point

The public UI facade is in `main/ui/ui.h`. Hardware-specific work belongs behind
`main/ui/ui_board.h`. The shipped weak functions return
`ESP_ERR_NOT_SUPPORTED`, and the facade falls back to structured ESP-IDF logs.
To connect the official display/LVGL port later:

1. add the reviewed vendor/managed components under `components/` or the IDF
   component manager;
2. provide strong implementations of `ui_board_init`, `ui_board_show_state`,
   `ui_board_play_boot_animation`, `ui_board_show_face`, `ui_board_show_user`,
   `ui_board_show_error`, and `ui_board_set_brightness`;
3. make the adapter own LVGL display/touch initialization and translate the
   state enum into animations; calls through the facade are serialized, but an
   adapter that queues work must copy borrowed string arguments and use its own
   LVGL task lock;
4. implement `ui_board_play_sound` only when the real audio BSP is introduced.

No Waveshare BSP or LVGL source has been copied into this skeleton, and no
panel/touch/audio pin mapping is fabricated.

## Source layout

```text
main/
├── app_main.c             startup and task wiring
├── app_state.[ch]         thread-safe complete state enum/store
├── protocol/              bounded cJSON command/event codec
├── comms/usb_serial.[ch]  selectable USB Serial/JTAG or UART JSONL framing
├── comms/heartbeat.[ch]   periodic uptime report
├── input/buttons.[ch]     optional debounced GPIO inputs
└── ui/                    UI facade, state/face modules, weak board adapter
```
