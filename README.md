# 老人陪伴对话机器人

这是项目规格中 Phase 0–2 的第一阶段实现：一个能在没有真实硬件、云端 LLM 或音频设备时运行和测试的原型。

当前包含：

- Raspberry Pi 端 FastAPI 服务与 SQLite 数据库；
- `MockLLM` 文本对话闭环和 mock 音频边界；
- 设备状态机、USB 串口 JSON Lines 协议与 Python 串口客户端；
- 可交互的 `mock_esp32.py`；
- ESP-IDF 固件骨架（状态、协议、心跳、按键和可替换 UI 适配层）；
- 协议、数据库、硬件边界与路线图文档。

## 快速开始

要求 Python 3.11 或更高版本。在仓库根目录执行：

Windows 10/11 用户请先阅读 [`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md)，其中包含 PowerShell、Python、ESP-IDF、烧录和串口联调的完整步骤。

```bash
make setup
cp pi-backend/.env.example pi-backend/.env
make run
```

服务默认位于 `http://127.0.0.1:8000`，交互文档位于 `/docs`。

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/chat/text \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user_001","text":"我年轻的时候在纺织厂上班"}'
```

运行测试：

```bash
make test
```

生成一段本地 mock 音频：

```bash
python3 tools/mock_audio.py --output /tmp/mock-input.wav --duration 1.5
```

ESP32 模拟器用法见 [`tools/README.md`](tools/README.md)，固件构建和厂家 BSP 边界见 [`esp32-firmware/README.md`](esp32-firmware/README.md)。

## 仓库结构

```text
docs/               项目规格、协议、数据库和路线图
pi-backend/         Raspberry Pi FastAPI 后端
esp32-firmware/     ESP-IDF 固件
tools/              无硬件联调工具
assets/             后续表情、提示音和图标资源
web-admin/          后续阶段预留
```

## 当前边界

本阶段不会持久化原始音频或视频；尚未接入真实 STT、LLM、TTS、人脸识别或自传生成。圆形 ESP32-S3-Touch-AMOLED-1.43C 已接入原生 LVGL 动态表情，并提供板载双麦克风到内置喇叭的三秒录音回放验证；这只证明本地音频硬件链路，不代表云端语音对话已经完成。详细烧录与 BOOT 键重复测试方法见固件 README。

详细目标与约束以 [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) 为准。
