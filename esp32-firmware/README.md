# ESP32-S3 firmware for the 1.43C round terminal

This directory contains the ESP-IDF skeleton for the round-screen terminal in
`docs/PROJECT_SPEC.md`. Its current responsibility is deliberately small:

- maintain every specified device state;
- receive bounded JSON Lines commands from the Raspberry Pi;
- expose state, face, user, error, brightness, and prompt-sound UI actions;
- report periodic heartbeats and debounced WAKE/STOP events;
- render native animated expressions on the 466 x 466 round AMOLED;
- verify the built-in ES7210 microphones and ES8311 speaker path.

The microphone/speaker record-and-replay path is now real hardware. Touch,
camera, cloud STT/LLM/TTS, and named prompt sounds are still outside this
verification build; the JSON `sound` command therefore remains a log mock.

## Recommended toolchain

Use the vendor demo as the integration baseline:

- [Waveshare ESP32-S3-Touch-AMOLED-1.43C documentation](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.43C)
- [Waveshare official demo repository](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.43C), currently containing an `espidf_v5.5.3` example
- ESP-IDF 5.5.x, preferably 5.5.3 to match that demo

The firmware uses ESP-IDF 5.5.3, LVGL 9.5, `esp_lvgl_adapter`, the SH8601
display driver, and the same `codec_board` 2.0.0 / `esp_codec_dev` 1.5.4 audio
stack used by the vendor's ESP-IDF audio example.

The module is ESP32-S3-PICO-1-N8R8 with a 466 x 466 AMOLED and CST820 touch
controller. The audio verification task uses the on-board BOOT key (GPIO0) to
repeat a test; the separately configurable external WAKE and STOP inputs stay
disabled by default.

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
{"type":"sound","name":"speaker_test"}
{"type":"face","emotion":"demo"}
```

The accepted state values are:

```text
BOOTING IDLE FACE_SCANNING USER_RECOGNIZED UNKNOWN_USER LISTENING THINKING
SPEAKING CONFUSED COMFORT PRIVACY_MIC_OFF PRIVACY_CAMERA_OFF NETWORK_ERROR
API_ERROR LOW_POWER
```

`face` accepts `smile`/`happy`, `sad`, `surprised`, `confused`, `comfort`/`gentle`,
`wink`, `sleepy` and the special `demo`, which makes the device cycle through
every animated expression until another face, user or error command arrives.
`sound` currently plays only `speaker_test`; other names are reported as not
supported. Expression details are in `docs/EXPRESSION_UI.md`.

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

With `ELDER_AUDIO_LOOPBACK_TEST` enabled, GPIO0 is reserved for the on-board
BOOT key. Do not assign an external WAKE/STOP input to GPIO0 at the same time.

## On-board microphone and speaker test

The default build runs one test automatically after startup:

1. wait for the short cue, then start speaking when the listening expression appears;
2. speak for three seconds;
3. listen while the speaking expression replays the recording;
4. press and release BOOT to repeat without reflashing.

The speaker keeps the vendor example's 100% volume. Recording uses the ES7210's
native four-channel, 16-bit TDM frame at 30 dB analog gain; playback is closed
during capture, then the buffer is converted to two-channel, 16-bit audio before
the ES8311 is reopened. Live board telemetry identifies TDM slots 0 and 2 as
the two physical microphone signals; the nearly empty slots 1 and 3 remain in
the raw capture for format correctness and diagnostics. The AEC/reference and
unused logical channels are held at 0 dB while the two physical microphones use
30 dB. Before replay, the firmware applies a 100 Hz high-pass and 3.8 kHz
Butterworth low-pass, estimates noise and voice levels from the whole recording,
selects the better-SNR microphone, and uses a 60 ms look-ahead soft expander
with an 80 ms tail hold. Automatic gain uses only detected voice frames and is capped
at 2x; a soft-knee limiter avoids harsh clipping. The `audio_quality` JSON line
reports p10 noise, p80 voice level, SNR proxy, active/suppressed frame counts,
quiet-section attenuation, digital gain, limiting count, and output peak.
The listening expression is not shown until the microphone is open, and the
first 120 ms of microphone data is retained as pre-roll rather than discarded,
so speech beginning near the end of the cue is preserved.
Duration, volume, and microphone gain are configurable under
`Component config -> Elder companion firmware -> On-board audio verification`.
This loopback proves only the local microphone/codec/amplifier/speaker path; it
does not yet prove network speech recognition, Kimi, or speech synthesis.

To check the speaker on its own, send `{"type":"sound","name":"speaker_test"}`
or run `tools/device_check.py --sound speaker_test`. The firmware plays a 13.1 s
clip embedded from `main/audio/speaker_test.pcm` (16 kHz mono PCM16): a Chinese
voice prompt tuned for the small speaker (300 Hz high-pass, presence boost,
compression, 6 dB headroom) to judge intelligibility, an ascending chime, a 150 Hz-6 kHz sweep that
exposes rattle or distortion, and a closing prompt. It runs after any
record/replay cycle in progress and shows the speaking expression. Regenerate
the clip on macOS with `python3 tools/make_speaker_test_clip.py`.

The board's two side keys are BOOT and PWR. Only BOOT triggers the repeat test;
PWR controls board power and is not an application input.

## UI / Waveshare BSP boundary

The public UI facade is in `main/ui/ui.h`; hardware-specific rendering remains
behind `main/ui/ui_board.h`. `components/elder_round_bsp` owns the 1.43C QSPI
panel and LVGL adapter. The audio verification service is deliberately separate
from `ui_board_play_sound`, so later TTS streaming can replace the temporary
loopback without rewriting the expression renderer or JSON protocol.

## Source layout

```text
main/
├── app_main.c             startup and task wiring
├── app_state.[ch]         thread-safe complete state enum/store
├── protocol/              bounded cJSON command/event codec
├── comms/usb_serial.[ch]  selectable USB Serial/JTAG or UART JSONL framing
├── comms/heartbeat.[ch]   periodic uptime report
├── audio/audio_loopback.* ES7210 -> PSRAM -> ES8311 verification, speaker test
├── audio/speaker_test.pcm  embedded speaker test clip
├── input/buttons.[ch]     optional debounced GPIO inputs
└── ui/                    UI facade and native round-display expressions
```
