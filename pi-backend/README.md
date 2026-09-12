# Raspberry Pi Backend

Phase 0/1 backend for the elder companion robot. It runs locally with FastAPI,
SQLite, a deterministic `MockLLM`, and mock STT/TTS/audio boundaries. No API key
or hardware is needed, and no raw audio is saved.

## Requirements

- Python 3.11+
- Linux, macOS, or Raspberry Pi OS

## Start locally

```bash
cd pi-backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m app
```

The SQLite file is created automatically at `data/elder_companion.db`.

## Try the API

```bash
curl http://127.0.0.1:8000/health

curl -X POST http://127.0.0.1:8000/chat/text \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"demo-user","display_name":"张奶奶","text":"今天天气真好"}'

curl http://127.0.0.1:8000/device/state
```

`user_id` is optional; when omitted, the configured `default-user` visitor is
used and both turns are marked `should_remember=false`.
Unknown valid user IDs are created automatically. A successful request stores
exactly one `user` row and one `assistant` row in `conversation_turns` in the
same transaction. The mock audio boundary is exercised in memory and the
returned device state is `SPEAKING`.

Interactive documentation is available at <http://127.0.0.1:8000/docs>.

## Optional Qwen text backend (Alibaba Cloud)

The default remains the local `MockLLM`. To test a single real text turn through
Alibaba Cloud Bailian, put the following values in the local `pi-backend/.env`
file:

```dotenv
ELDER_ROBOT_LLM_BACKEND=qwen
ELDER_ROBOT_QWEN_API_KEY=your-local-api-key
ELDER_ROBOT_QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ELDER_ROBOT_QWEN_MODEL=qwen-plus
ELDER_ROBOT_QWEN_MAX_TOKENS=2048
ELDER_ROBOT_QWEN_ENABLE_THINKING=false
```

Bailian exposes an OpenAI-compatible endpoint, so the client only needs a base
URL, a bearer key, and a model name. Keep `ELDER_ROBOT_QWEN_ENABLE_THINKING`
set to `false`: Qwen3 models reject non-streaming requests while thinking is on.
Omit the variable entirely to fall back to the model default. Outside mainland
China, use `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` instead.

Kimi remains available as `ELDER_ROBOT_LLM_BACKEND=kimi` with the
`ELDER_ROBOT_KIMI_*` variables; see `.env.example` for the full list.

Do not send the API key through chat, put it in source code, or commit `.env`.
The repository ignores `pi-backend/.env`. The request sends the companion system
prompt and the current user text only; conversation-history retrieval is not part
of this single-turn integration. It also does not yet replace the mock STT, TTS,
or audio playback boundaries.

The test suite is isolated from `.env` and from `ELDER_ROBOT_` variables, so
enabling a real backend locally never makes `pytest` issue billable requests.

## Optional ESP32 connection

Device communication is disabled by default, so the API starts without
hardware. To connect the TCP simulator, first run it from the repository root:

```bash
pi-backend/.venv/bin/python tools/mock_esp32.py
```

Then set these values in `pi-backend/.env` and start FastAPI normally:

```dotenv
ELDER_ROBOT_DEVICE_TRANSPORT=mock_tcp
ELDER_ROBOT_DEVICE_MOCK_TCP_HOST=127.0.0.1
ELDER_ROBOT_DEVICE_MOCK_TCP_PORT=8765
```

For a USB/UART device, use:

```dotenv
ELDER_ROBOT_DEVICE_TRANSPORT=serial
ELDER_ROBOT_DEVICE_SERIAL_PORT=/dev/ttyACM0
ELDER_ROBOT_DEVICE_SERIAL_BAUDRATE=115200
```

The reader connects and reconnects in the background. An absent device never
blocks API startup. While connected, backend state changes are sent to the
ESP32, and ESP32 button, privacy, and heartbeat messages update the same state
returned by `GET /device/state`. Shutdown stops the reader and closes the link.

The HTTP API has no authentication in this prototype and defaults to
`127.0.0.1`. Do not bind it to `0.0.0.0` or expose it to a LAN until an
authentication layer is added.

## Test

```bash
cd pi-backend
pytest -q
```

Tests use isolated temporary SQLite databases and cover schema creation, health,
device state, validation, the chat persistence pair, repeated turns, and
rollback behavior when the model fails.

## Database tables

All seven first-version tables are created on startup:

- `users`
- `face_profiles`
- `conversation_turns`
- `daily_summaries`
- `memory_facts`
- `life_events`
- `autobiography_chapters`

Only `users` and `conversation_turns` are written by the phase-one chat flow.
