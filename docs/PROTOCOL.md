# Raspberry Pi ↔ ESP32 JSON Lines 协议

## 传输与帧格式

- 第一阶段固件链路：ESP32-S3 USB Serial/JTAG（默认）或硬件 UART；UART 默认建议 `115200 8N1`。未来可在不改消息格式的前提下替换为 USB CDC；
- 编码：UTF-8；
- 一行只包含一个 JSON 对象，以 `\n` 结束；接收端兼容 `\r\n`；
- 单帧不得包含裸换行；文本中的换行必须使用 JSON 转义；
- 第一阶段单个 JSON payload 最大为 2048 字节（不计结尾的 LF/CRLF），超长、非对象、未知类型、重复字段、额外字段或字段类型错误的帧应丢弃并记录错误，但不能让接收任务退出；超长串口数据应一直丢弃到下一 LF 后再恢复解析；
- 双方均不得在 JSON Lines 数据通道输出普通日志。固件日志与协议共用 UART 时，生产配置需关闭日志或改用独立端口。

协议当前为本地可信设备协议，不包含身份认证。`mock_esp32.py` 的 TCP 模式只允许本机开发使用；若未来正式迁移到 TCP/Wi-Fi，需要增加版本握手、认证和重放保护。

## Raspberry Pi → ESP32

### 状态

```json
{"type":"state","state":"LISTENING"}
```

`state` 可取：`BOOTING`、`IDLE`、`FACE_SCANNING`、`USER_RECOGNIZED`、`UNKNOWN_USER`、`LISTENING`、`THINKING`、`SPEAKING`、`CONFUSED`、`COMFORT`、`PRIVACY_MIC_OFF`、`PRIVACY_CAMERA_OFF`、`NETWORK_ERROR`、`API_ERROR`、`LOW_POWER`。

### 其他显示/反馈命令

```json
{"type":"face","emotion":"smile","intensity":0.8}
{"type":"user","recognized":true,"display_name":"张奶奶"}
{"type":"error","code":"NETWORK_ERROR","message":"网络连接失败"}
{"type":"display","brightness":70}
{"type":"sound","name":"wake"}
```

约束：`intensity` 为 `0.0..1.0`，`brightness` 为 `0..100`。固件按 UTF-8 wire bytes 限制字符串：emotion/error code/sound name 最多 256 字节，display name 最多 512 字节；error message 由 2048 字节整帧上限约束。

## ESP32 → Raspberry Pi

```json
{"type":"event","event":"WAKE_BUTTON_PRESSED"}
{"type":"event","event":"STOP_BUTTON_PRESSED"}
{"type":"privacy","mic_muted":true}
{"type":"privacy","camera_blocked":true}
{"type":"touch","event":"SCREEN_TAPPED","x":212,"y":180}
{"type":"heartbeat","uptime_ms":123456}
```

隐私帧可以同时带 `mic_muted` 和 `camera_blocked`，也可以只带发生变化的字段；至少需要包含其中一个。`uptime_ms` 是 ESP32 启动后的单调时钟，不是墙上时钟。

## 状态与隐私优先级

麦克风静音和摄像头遮挡是独立事实，不会因为普通状态切换而被清除。设备快照始终返回两者；安全待机时 UI 显示相应 `PRIVACY_*` 状态。麦克风静音只禁止 `LISTENING`，摄像头遮挡只禁止 `FACE_SCANNING`，不会互相禁用另一类能力。解除开关后应回到安全的 `IDLE`（或另一仍开启的隐私提示），而不是自动恢复录音、识别或播放。

建议的普通对话序列：

```text
IDLE → LISTENING → THINKING → SPEAKING → IDLE
```

`mic_muted=true` 时禁止进入 `LISTENING`。`STOP_BUTTON_PRESSED` 应停止当前动作并回到 `IDLE`（若麦克风仍静音，则显示 `PRIVACY_MIC_OFF`）。

## 兼容性

解析器对当前消息模型执行严格验证，旧端会拒绝任何新增字段，因此字段增删或含义变化都必须配合协议版本升级。新增独立消息类型不会破坏已有消息，但旧端会将其报告为 unsupported。第一阶段尚未加入显式 `version` 帧，接入真实硬件前应补充握手和能力协商。
