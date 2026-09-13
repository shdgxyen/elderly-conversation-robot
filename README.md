# 老人陪伴对话机器人

面向老人的陪伴对话机器人：树莓派负责对话、记忆与数据，ESP32-S3 圆形屏终端负责表情、按键和板载音频，两者通过 USB 串口上的 JSON Lines 协议通信。

核心交互：对话开始前，机器人通过摄像头捕捉老人的面部表情，判断高兴还是难过，再据此调整语气、给予安慰。

项目已在真实硬件 **微雪 ESP32-S3-Touch-AMOLED-1.43C** 上运行：动态表情、串口协议与心跳、板载麦克风和喇叭均已实机验证。

## 当前能力

**ESP32-S3 圆屏终端（实机运行）**

- 466 × 466 圆形 AMOLED 上的矢量动态表情：15 种业务状态（待机、聆听、思考、说话、安慰、隐私提示、网络错误等）和 7 种独立表情（开心、难过、惊讶、疑惑、安慰、眨眼、犯困）；
- 表情之间平滑变形过渡，随机眨眼与视线张望；一条指令即可让设备自己循环展示全部表情；
- USB 串口 JSON Lines 协议：状态、表情、用户、错误、亮度、声音指令，设备回报心跳与事件；
- 板载音频：上电自动录音 3 秒并由内置喇叭回放（BOOT 键可重复），以及内置喇叭测试音。

**树莓派后端**

- FastAPI 服务与 SQLite 数据库，文本对话持久化；
- 对话模型默认离线 `MockLLM`，可切换阿里云百炼通义千问或 Kimi（单轮文本），配置见 [`pi-backend/README.md`](pi-backend/README.md)；
- 设备状态机与 Python 串口客户端，另有无需硬件的 `mock_esp32.py` 模拟器。

**工具与文档**

- [`tools/device_check.py`](tools/device_check.py)：连接真实设备逐个查看表情、启动表情轮播、播放喇叭测试音；
- 协议、数据库、硬件、Windows 开发环境与[圆屏表情实现](docs/EXPRESSION_UI.md)文档，以及教学方案和学生学习手册。

## 快速开始

### 后端（无需硬件）

要求 Python 3.11 或更高版本。Windows 10/11 用户请先阅读 [`docs/WINDOWS_SETUP.md`](docs/WINDOWS_SETUP.md)。在仓库根目录执行：

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

没有设备时，可用 [`tools/README.md`](tools/README.md) 中的 ESP32 模拟器联调串口协议。

### 连接真实设备

1. 按 [`esp32-firmware/README.md`](esp32-firmware/README.md) 用 ESP-IDF 5.5.3 编译并烧录固件。
2. 用 USB-C 连接电脑。上电后屏幕先播放惊讶动画，随后“嘀”一声开始录音 3 秒并回放，这是板载音频自检。
3. 关闭 Arduino IDE 串口监视器等占用串口的程序，然后运行实机检查工具：

```bash
pi-backend/.venv/bin/python tools/device_check.py                       # 逐个显示表情并确认
pi-backend/.venv/bin/python tools/device_check.py --demo                # 让设备自己循环展示全部表情
pi-backend/.venv/bin/python tools/device_check.py --sound speaker_test  # 播放喇叭测试音
```

## 硬件

| 部件 | 型号与说明 |
| --- | --- |
| 圆屏终端 | 微雪 ESP32-S3-Touch-AMOLED-1.43C，ESP32-S3-PICO-1 模组（8 MB Flash、8 MB PSRAM） |
| 屏幕 | 1.43 英寸 466 × 466 圆形 AMOLED，SH8601 驱动，QSPI 接口 |
| 音频 | ES7210 双麦克风采集，ES8311 编解码器与功放驱动内置喇叭 |
| 上位机 | Raspberry Pi；开发阶段可用 macOS、Windows 或 Linux 电脑代替 |

USB 口承载 JSON Lines 协议，ESP-IDF 应用日志走 UART0（GPIO43/44），两者分开以免日志混入协议。协议字段见 [`docs/PROTOCOL.md`](docs/PROTOCOL.md)，硬件边界见 [`docs/HARDWARE.md`](docs/HARDWARE.md)。

## 仓库结构

```text
docs/               项目规格、协议、数据库、硬件、表情实现、路线图与教学资料
pi-backend/         Raspberry Pi FastAPI 后端
esp32-firmware/     ESP-IDF 固件（1.43C 圆屏终端）
tools/              模拟器、实机检查与测试音生成工具
assets/             后续表情、提示音和图标资源
web-admin/          后续阶段预留
```

## 当前进度与下一步

- **已在实机完成**：圆屏动态表情与表情轮播、USB 串口协议与心跳、板载录音回放自检、喇叭测试音；
- **已在软件完成**：后端文本对话闭环与持久化，已接入通义千问 / Kimi 对话模型（单轮文本）；
- **下一步：API 联调**：接入语音识别 API，语音合成直接使用现成语音包，接入摄像头表情识别（高兴 / 难过，不做人脸身份识别），把表情判断、对话和圆屏表情串成完整流程。

项目不持久化原始音频或视频。阶段划分见 [`docs/ROADMAP.md`](docs/ROADMAP.md)，详细目标与约束以 [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md) 为准。
