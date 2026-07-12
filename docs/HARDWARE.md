# 第一阶段硬件边界

目标硬件为 Raspberry Pi 5 与微雪 ESP32-S3-Touch-AMOLED-1.43C，但 Phase 0–2 必须可以完全脱离硬件运行。

## 当前实现

- Raspberry Pi：FastAPI、SQLite、设备状态和串口协议；
- ESP32：ESP-IDF 任务、JSON Lines、心跳、按键事件和 UI 适配层；
- PC 开发：`mock_esp32.py` 模拟设备，`mock_audio.py` 生成测试 WAV。

## 已核对的板卡资料

微雪官方资料确认该板采用 ESP32-S3-PICO-1-N8R8，圆屏为 466×466 的 CO5300 QSPI AMOLED，触摸控制器为 CST820；板载音频包含 ES8311、ES7210 和双麦克风，用户 LED 位于 GPIO5。厂家同时提供 [1.43C 官方 Demo](https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-1.43C) 和 [ESP-IDF 指南](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.43C/Development-Environment-Setup-ESP-IDF)。

## 尚未绑定的硬件细节

产品外壳还会增加独立唤醒键和停止键，规格没有给出这些外接按键的最终 GPIO，也没有确定 USB CDC 接口选择，因此固件不会猜测这些参数。按键应通过 menuconfig 或板级适配文件配置；屏幕渲染先走 UI 抽象，接入厂家 BSP 后只替换该层。厂家当前仓库的 ESP-IDF 示例目录为 `espidf_v5.5.3`，并分别提供 LVGL 8 与 LVGL 9 示例；项目接板时应先锁定其中一套版本再引入依赖。

Phase 6 之前不实现板载双麦克风上行、小喇叭下行、回声消除或 USB Audio Class。第一阶段的 WAV 只用于测试接口边界，且运行时不默认保存任何用户音频。
