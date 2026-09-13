# 联调与实机检查工具

## 实机检查（真实 1.43C 圆屏终端）

`device_check.py` 通过 USB 串口与已烧录固件的设备通信，依赖 `make setup` 安装的 pyserial。使用前关闭 Arduino IDE 串口监视器等占用串口的程序：

```bash
pi-backend/.venv/bin/python tools/device_check.py                       # 逐个发送 7 种表情并确认
pi-backend/.venv/bin/python tools/device_check.py --auto --hold 8       # 自动轮播，不逐个确认
pi-backend/.venv/bin/python tools/device_check.py --demo                # 让设备自己循环展示全部表情
pi-backend/.venv/bin/python tools/device_check.py --sound speaker_test  # 播放内置喇叭测试音
pi-backend/.venv/bin/python tools/device_check.py --watch 30 -v         # 只监听心跳与音频自检输出
```

默认自动选择 `/dev/cu.usbmodem*`（macOS）或 `/dev/ttyACM*`（Linux），Windows 需用 `--port COM5` 指定。脚本打开串口时保持 DTR/RTS 不变，不会让板子重启。

`make_speaker_test_clip.py` 用 macOS 自带的中文语音重新生成固件内置的喇叭测试音 `esp32-firmware/main/audio/speaker_test.pcm`，改完需重新编译烧录固件。

## ESP32 模拟器

先安装后端依赖，然后启动模拟器：

```bash
make setup
make mock-esp32
```

模拟器默认在 `127.0.0.1:8765` 监听 TCP。TCP 只替代串口传输层，线上内容仍是完全相同的 UTF-8 JSON Lines。交互终端支持 `wake`、`stop`、`mic mute|unmute`、`camera block|unblock`、`touch`、`heartbeat` 和 `status`。

后端代码可直接使用测试传输：

```python
from app.device import ESP32SerialClient

client = ESP32SerialClient.for_tcp_mock("127.0.0.1", 8765)
client.connect()
client.start()
```

最简单的人工协议检查也可以使用 `nc 127.0.0.1 8765` 连接模拟器，然后发送：

```json
{"type":"state","state":"LISTENING"}
```

此 TCP 端口只用于本机开发，不带认证，不能暴露到局域网或互联网。运行参数见：

```bash
pi-backend/.venv/bin/python tools/mock_esp32.py --help
```

## Mock 音频

`mock_audio.py` 生成确定性的单声道 PCM16 WAV，不访问麦克风，也不包含用户数据：

```bash
python3 tools/mock_audio.py \
  --output /tmp/mock-input.wav \
  --duration 1.5 \
  --sample-rate 16000 \
  --frequency 440
```

`--frequency 0` 会生成静音。后端自身的 MockSTT/TTS/播放器使用内存字节，不依赖这个 WAV，也不会默认写入音频文件。

