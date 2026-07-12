# 无硬件联调工具

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

