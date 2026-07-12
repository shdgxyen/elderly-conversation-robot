# 老人陪伴对话机器人项目规格说明

> 版本：v0.1  
> 用途：作为后续使用 Codex 构建代码时的项目说明、架构边界和开发任务拆解。  
> 当前目标：先完成一个可以运行的第一版原型，而不是一次性做成最终产品。

---

## 1. 项目一句话定义

本项目是一个面向老人的桌面式小型互动机器人，核心能力是：

1. 能和老人进行语音聊天；
2. 能通过小圆屏显示表情和状态；
3. 能识别人脸，用于确认是谁在使用；
4. 能保存经过授权的对话内容；
5. 能从长期对话中整理老人经历；
6. 能逐步生成老人的“人生自传”。

产品形态参考汽车中控台上的小型互动机器人：小巧、圆润、有表情、可语音交互。

---

## 2. 当前确定的硬件方案

### 2.1 整体形态

机器人分为两部分：

```text
小圆形屏幕机器人本体
+
底座里的树莓派中转站
```

也可以理解为：

```text
机器人头部 / 前端终端：ESP32-S3 1.43C 屏幕机器人
机器人底座 / 本地服务器：Raspberry Pi 5
```

---

### 2.2 屏幕机器人本体

已确定使用：

```text
微雪 ESP32-S3-Touch-AMOLED-1.43C
```

它在本项目中的角色是：

```text
小圆脸
表情显示
触摸交互
板载双麦克风采集
小喇叭播放
状态灯 / 按键控制
与树莓派通信
```

屏幕机器人上应包含：

| 元件 | 作用 |
|---|---|
| ESP32-S3-Touch-AMOLED-1.43C | 屏幕、触摸、麦克风、音频接口、ESP32 主控 |
| 小喇叭 | 播放机器人语音 |
| 小摄像头 | 只做人脸识别 |
| 唤醒按钮 | 开始聊天 |
| 停止按钮 | 停止录音或停止播放 |
| 麦克风静音开关 | 物理隐私控制 |
| 摄像头滑盖 | 物理隐私控制 |
| 状态 LED | 提示录音、摄像头、联网、隐私模式 |
| 外壳结构 | 小圆形机器人头部和底座 |

---

### 2.3 树莓派底座

推荐使用：

```text
Raspberry Pi 5 8GB
```

预算充足可以使用：

```text
Raspberry Pi 5 16GB
```

树莓派在本项目中的角色是：

```text
本地服务器
API 中转站
语音识别调用端
大模型调用端
语音合成调用端
人脸识别处理端
数据库和长期记忆存储端
人生自传生成端
```

树莓派上应包含：

| 元件 | 作用 |
|---|---|
| Raspberry Pi 5 | 本地中转站和主计算单元 |
| NVMe SSD | 保存数据库、日志、自传草稿、配置 |
| 官方电源 | 稳定供电 |
| 主动散热 | 保证长时间运行 |
| M.2 HAT | 连接 NVMe SSD |
| 摄像头连接线 / USB 线 | 连接机器人头部的摄像头 |
| 与 ESP32 的 USB / UART 连接 | 控制屏幕、传输状态、未来传输音频 |

---

## 3. 最终分工原则

一句话原则：

```text
树莓派负责“听懂、思考、识别、存储、生成”
ESP32 负责“显示、采集、播放、交互、状态反馈”
```

---

## 4. 树莓派与 ESP32 分工表

| 功能 | 树莓派 | ESP32-S3 1.43C |
|---|---:|---:|
| 外部 API 调用 | ✅ | ❌ |
| LLM 对话生成 | ✅ | ❌ |
| STT 语音识别 | ✅ | ❌ |
| TTS 语音合成 | ✅ | ❌ |
| 对话流程调度 | ✅ | ❌ |
| 对话文本存储 | ✅ | ❌ |
| 长期记忆提取 | ✅ | ❌ |
| 自传草稿生成 | ✅ | ❌ |
| 人脸识别 | ✅ | ❌ |
| 摄像头物理安装 | ❌ | ✅ |
| 麦克风物理安装 | ❌ | ✅ |
| 麦克风音频采集 | 可接收处理 | ✅ |
| 扬声器物理安装 | ❌ | ✅ |
| 扬声器播放 | 生成音频 | ✅ |
| 圆形屏表情 | ❌ | ✅ |
| 触摸交互 | ❌ | ✅ |
| 按键读取 | 可选 | ✅ |
| 静音开关读取 | 可选 | ✅ |
| 摄像头滑盖读取 | 可选 | ✅ |
| 状态 LED | ❌ | ✅ |
| API Key 保存 | ✅ | ❌ |
| 数据库 | ✅ | ❌ |
| Web 管理后台 | ✅ | ❌ |

---

## 5. 摄像头功能边界

当前摄像头只做一件事：

```text
人脸识别
```

### 5.1 摄像头允许做

1. 判断是否有人脸；
2. 判断是不是已经登记的老人；
3. 根据识别结果使用正确称呼；
4. 未识别时进入普通访客模式；
5. 摄像头被遮挡时关闭识别功能。

### 5.2 摄像头暂时不做

1. 不做全天候监控；
2. 不做录像保存；
3. 不做情绪识别；
4. 不做摔倒检测；
5. 不做远程直播；
6. 不做医疗判断。

### 5.3 人脸识别流程

```text
摄像头看到人脸
        ↓
树莓派进行本地人脸识别
        ↓
识别为老人本人
        ↓
树莓派通知 ESP32 显示欢迎表情
        ↓
机器人使用老人称呼开始对话
```

未识别时：

```text
摄像头看到人脸
        ↓
树莓派无法匹配
        ↓
ESP32 显示普通欢迎表情
        ↓
机器人进入访客模式，不展示私人记忆
```

---

## 6. 音频方案

### 6.1 产品目标方案

优先使用 1.43C 自带的音频能力：

```text
1.43C 板载双麦克风
+
1.43C 音频 codec / 功放
+
外接小喇叭
```

音频链路目标：

```text
老人说话
  ↓
1.43C 双麦克风采集
  ↓
ESP32 将音频传给树莓派
  ↓
树莓派调用 STT
  ↓
树莓派调用 LLM
  ↓
树莓派调用 TTS
  ↓
树莓派将语音音频发回 ESP32
  ↓
1.43C 通过小喇叭播放
```

---

### 6.2 音频实现路线

当前有两个可选技术路线。

#### 路线 A：USB Audio Class，目标正式方案

目标效果：

```text
1.43C 插到树莓派后，树莓派识别到：
- 一个 USB 麦克风
- 一个 USB 扬声器
- 一个串口控制设备
```

优点：

1. 外观最干净；
2. 树莓派端音频处理简单；
3. 不依赖 Wi-Fi；
4. 延迟和稳定性更好；
5. 更适合产品化。

难点：

1. ESP32 固件复杂；
2. 需要使用 ESP-IDF；
3. 需要实现 USB Audio Class；
4. 需要处理音频缓存、采样率、延迟和回声。

#### 路线 B：自定义音频流，开发验证方案

方式：

```text
ESP32 采集 PCM 音频
        ↓
通过 USB 串口 / WebSocket / TCP 发给树莓派
        ↓
树莓派处理后把音频流发回 ESP32
        ↓
ESP32 播放
```

优点：

1. 协议可控；
2. 方便快速验证；
3. 不需要一开始完整实现 USB 声卡。

缺点：

1. 音频卡顿风险更高；
2. 延迟需要仔细调；
3. 串口带宽可能成为瓶颈；
4. 后续仍然可能需要改成 UAC。

---

### 6.3 第一版建议

为了不让项目卡死在音频底层，开发顺序建议：

```text
第 1 步：先跑通树莓派后端对话流程，允许 mock 音频输入输出
第 2 步：跑通 ESP32 表情屏和状态通信
第 3 步：接入摄像头做人脸识别
第 4 步：再接入 1.43C 板载麦克风和小喇叭
第 5 步：最终优化成 USB Audio Class 或稳定的自定义音频流
```

外置 USB 麦克风 / USB 小音箱只作为调试备用，不进入最终产品形态。

---

## 7. 系统总体架构

```text
┌────────────────────────────────────────────┐
│              屏幕机器人本体                 │
│                                            │
│  ESP32-S3-Touch-AMOLED-1.43C               │
│  ├── 圆形 AMOLED 表情屏                    │
│  ├── 触摸输入                              │
│  ├── 双麦克风                              │
│  ├── 音频 Codec / 功放                     │
│  ├── 小喇叭                                │
│  ├── 按键 / 静音开关 / LED                 │
│  └── 与树莓派通信                          │
│                                            │
│  小型摄像头                                │
│  └── 只用于人脸识别                        │
└───────────────────┬────────────────────────┘
                    │
                    │ USB / UART / 内部线束
                    │
┌───────────────────▼────────────────────────┐
│                 树莓派底座                  │
│                                            │
│  Raspberry Pi 5                            │
│  ├── 设备通信服务                          │
│  ├── 人脸识别服务                          │
│  ├── 语音识别 STT                          │
│  ├── LLM 对话服务                          │
│  ├── 语音合成 TTS                          │
│  ├── 对话数据库                            │
│  ├── 长期记忆系统                          │
│  ├── 自传生成系统                          │
│  └── 本地 Web 管理后台                     │
└────────────────────────────────────────────┘
```

---

## 8. 状态机设计

机器人至少需要以下状态：

| 状态 | 说明 | 屏幕表现 |
|---|---|---|
| `BOOTING` | 启动中 | 开机动画 |
| `IDLE` | 待机 | 微笑、眨眼 |
| `FACE_SCANNING` | 正在人脸识别 | 轻微注视动画 |
| `USER_RECOGNIZED` | 识别到老人 | 开心欢迎 |
| `UNKNOWN_USER` | 未识别用户 | 普通欢迎 |
| `LISTENING` | 正在听老人说话 | 认真聆听表情 |
| `THINKING` | 正在调用模型 | 思考动画 |
| `SPEAKING` | 正在说话 | 嘴巴动 |
| `CONFUSED` | 没听清 | 疑惑表情 |
| `COMFORT` | 安慰语气 | 温和表情 |
| `PRIVACY_MIC_OFF` | 麦克风关闭 | 麦克风关闭图标 |
| `PRIVACY_CAMERA_OFF` | 摄像头关闭 | 摄像头关闭图标 |
| `NETWORK_ERROR` | 网络异常 | 抱歉表情 |
| `API_ERROR` | API 异常 | 抱歉表情 |
| `LOW_POWER` | 低功耗/低亮度 | 暗屏待机 |

---

## 9. 树莓派与 ESP32 通信协议

第一版建议使用：

```text
USB 串口 + JSON Lines
```

也就是一行一个 JSON：

```json
{"type":"state","state":"LISTENING"}
{"type":"event","event":"WAKE_BUTTON_PRESSED"}
```

---

### 9.1 树莓派发送给 ESP32

#### 设置状态

```json
{
  "type": "state",
  "state": "LISTENING"
}
```

#### 设置表情

```json
{
  "type": "face",
  "emotion": "smile",
  "intensity": 0.8
}
```

#### 显示用户欢迎

```json
{
  "type": "user",
  "recognized": true,
  "display_name": "张奶奶"
}
```

#### 显示错误

```json
{
  "type": "error",
  "code": "NETWORK_ERROR",
  "message": "网络连接失败"
}
```

#### 设置亮度

```json
{
  "type": "display",
  "brightness": 70
}
```

#### 播放提示音

```json
{
  "type": "sound",
  "name": "wake"
}
```

---

### 9.2 ESP32 发送给树莓派

#### 唤醒按钮

```json
{
  "type": "event",
  "event": "WAKE_BUTTON_PRESSED"
}
```

#### 停止按钮

```json
{
  "type": "event",
  "event": "STOP_BUTTON_PRESSED"
}
```

#### 麦克风静音

```json
{
  "type": "privacy",
  "mic_muted": true
}
```

#### 摄像头滑盖关闭

```json
{
  "type": "privacy",
  "camera_blocked": true
}
```

#### 触摸屏事件

```json
{
  "type": "touch",
  "event": "SCREEN_TAPPED",
  "x": 212,
  "y": 180
}
```

#### 心跳

```json
{
  "type": "heartbeat",
  "uptime_ms": 123456
}
```

---

## 10. 树莓派后端模块设计

树莓派后端建议使用 Python 实现。

推荐技术栈：

```text
Python 3.11+
FastAPI
SQLite
SQLAlchemy / SQLModel
OpenCV
本地文件存储
外部 STT / LLM / TTS API
```

---

### 10.1 后端模块

```text
pi-backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── device/
│   │   ├── serial_client.py
│   │   ├── device_state.py
│   │   └── protocol.py
│   ├── voice/
│   │   ├── recorder.py
│   │   ├── stt.py
│   │   ├── tts.py
│   │   └── audio_player.py
│   ├── llm/
│   │   ├── chat_client.py
│   │   ├── prompts.py
│   │   └── safety.py
│   ├── memory/
│   │   ├── extractor.py
│   │   ├── store.py
│   │   └── retriever.py
│   ├── biography/
│   │   ├── chapter_planner.py
│   │   ├── draft_generator.py
│   │   └── fact_checker.py
│   ├── face/
│   │   ├── camera.py
│   │   ├── detector.py
│   │   ├── recognizer.py
│   │   └── registry.py
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/
│   └── web/
│       ├── routes.py
│       └── schemas.py
├── tests/
├── scripts/
├── requirements.txt
└── README.md
```

---

## 11. ESP32 固件模块设计

ESP32 建议使用 ESP-IDF。  
不建议第一版只用 Arduino，因为后续音频、USB、LVGL、任务调度都更适合 ESP-IDF。

```text
esp32-firmware/
├── CMakeLists.txt
├── main/
│   ├── app_main.c
│   ├── app_state.c
│   ├── app_state.h
│   ├── protocol/
│   │   ├── protocol.c
│   │   └── protocol.h
│   ├── ui/
│   │   ├── ui_main.c
│   │   ├── ui_faces.c
│   │   ├── ui_states.c
│   │   └── ui_assets/
│   ├── input/
│   │   ├── buttons.c
│   │   ├── touch.c
│   │   └── privacy_switch.c
│   ├── audio/
│   │   ├── mic_capture.c
│   │   ├── speaker_playback.c
│   │   └── audio_bridge.c
│   ├── comms/
│   │   ├── usb_serial.c
│   │   └── heartbeat.c
│   └── led/
│       └── status_led.c
├── components/
└── README.md
```

---

## 12. 数据库设计

第一版使用 SQLite。

### 12.1 users

保存老人基本信息。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 用户 ID |
| display_name | string | 称呼 |
| full_name | string | 姓名，可选 |
| birth_year | int | 出生年份，可选 |
| preferred_language | string | 普通话 / 方言备注 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

---

### 12.2 face_profiles

保存人脸识别资料。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 人脸资料 ID |
| user_id | string | 关联老人 |
| embedding_path | string | 本地人脸向量文件 |
| created_at | datetime | 创建时间 |
| enabled | bool | 是否启用 |

---

### 12.3 conversation_turns

保存每轮对话。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 对话轮次 ID |
| user_id | string | 用户 ID |
| role | string | user / assistant |
| text | text | 文本内容 |
| source | string | voice / touch / system |
| created_at | datetime | 时间 |
| should_remember | bool | 是否用于长期记忆 |
| privacy_level | string | private / family / public |

---

### 12.4 daily_summaries

每日摘要。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 摘要 ID |
| user_id | string | 用户 ID |
| date | date | 日期 |
| summary | text | 当天聊了什么 |
| new_people | json | 新人物 |
| new_places | json | 新地点 |
| new_events | json | 新事件 |
| created_at | datetime | 创建时间 |

---

### 12.5 memory_facts

长期记忆。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 记忆 ID |
| user_id | string | 用户 ID |
| fact_type | string | person / place / event / preference |
| content | text | 记忆内容 |
| source_turn_ids | json | 来源对话 |
| confidence | float | 置信度 |
| verified_by_user | bool | 是否已确认 |
| created_at | datetime | 创建时间 |
| last_confirmed_at | datetime | 最后确认时间 |

---

### 12.6 life_events

人生事件。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 事件 ID |
| user_id | string | 用户 ID |
| title | string | 事件标题 |
| approximate_date | string | 大致时间 |
| location | string | 地点 |
| people | json | 相关人物 |
| description | text | 事件描述 |
| source_memory_ids | json | 来源记忆 |
| verified_by_user | bool | 是否已确认 |
| created_at | datetime | 创建时间 |

---

### 12.7 autobiography_chapters

自传章节。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 章节 ID |
| user_id | string | 用户 ID |
| title | string | 章节标题 |
| content | text | 章节草稿 |
| source_life_event_ids | json | 来源人生事件 |
| status | string | draft / review / approved |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

---

## 13. 对话流程

### 13.1 标准语音对话流程

```text
1. 老人靠近机器人
2. 摄像头做人脸识别
3. 识别成功后进入待机欢迎
4. 老人按下唤醒按钮或触摸屏幕
5. ESP32 通知树莓派：WAKE_BUTTON_PRESSED
6. 树莓派通知 ESP32：LISTENING
7. ESP32 采集麦克风音频并发送给树莓派
8. 树莓派调用 STT 得到文本
9. 树莓派把文本保存为 conversation_turn
10. 树莓派检索长期记忆
11. 树莓派调用 LLM 生成回复
12. 树莓派保存机器人回复
13. 树莓派调用 TTS
14. 树莓派通知 ESP32：SPEAKING
15. ESP32 播放 TTS 音频并显示说话表情
16. 播放结束后回到 IDLE 或继续 LISTENING
```

---

### 13.2 未识别用户流程

```text
1. 摄像头检测到人脸
2. 树莓派无法识别
3. ESP32 显示普通欢迎
4. 机器人可以简单聊天
5. 不读取老人私人记忆
6. 不展示自传内容
7. 不允许管理数据
```

---

### 13.3 隐私模式流程

麦克风关闭：

```text
1. 用户拨动静音开关
2. ESP32 发送 mic_muted=true
3. 树莓派停止录音
4. ESP32 显示麦克风关闭图标
```

摄像头关闭：

```text
1. 用户关闭摄像头滑盖
2. ESP32 发送 camera_blocked=true
3. 树莓派停止人脸识别
4. ESP32 显示摄像头关闭图标
```

---

## 14. LLM 提示词方向

### 14.1 陪伴对话系统提示词

```text
你是一名面向老人的温和陪伴型对话助手。
你的目标是让老人感到被尊重、被倾听、被陪伴。

要求：
1. 语气自然、慢一点、温和。
2. 不要像客服，不要连续问太多问题。
3. 每次最多追问一个问题。
4. 适合老人理解，避免复杂术语。
5. 当老人讲述过往经历时，要温和追问时间、地点、人物和感受。
6. 不要编造老人没有说过的人生经历。
7. 涉及健康、医疗、法律、财产时，不做专业判断，只建议联系家人或专业人士。
8. 老人要求“不记这个”时，必须尊重。
```

---

### 14.2 记忆提取提示词

```text
请从以下对话中提取可能需要长期保存的记忆。
只提取用户明确说过的信息，不要推测。

输出 JSON：
{
  "people": [],
  "places": [],
  "life_events": [],
  "preferences": [],
  "family_relations": [],
  "needs_confirmation": []
}
```

---

### 14.3 自传生成提示词

```text
你是一名温和、克制、尊重事实的自传编辑。
请根据已经确认的人生事件、长期记忆和对话摘录，生成第一人称自传草稿。

要求：
1. 只能使用给定材料。
2. 不得编造年份、地点、人物关系。
3. 时间不确定时使用模糊表达。
4. 语言朴素、真诚，不要过度文学化。
5. 保留老人自己的口吻。
6. 对痛苦经历要克制，不煽情。
7. 输出最后列出“需要老人确认的问题”。
```

---

## 15. 安全与隐私规则

第一版必须遵守：

1. 默认不保存原始音频；
2. 默认不保存视频；
3. 摄像头只做人脸识别；
4. 麦克风必须有物理静音开关；
5. 摄像头必须有物理滑盖；
6. API Key 只保存在树莓派；
7. ESP32 不保存老人隐私数据；
8. 老人说“不记这个”时，该轮对话不进入长期记忆；
9. 家属端查看内容必须有授权；
10. 自传导出前必须人工确认。

---

## 16. 代码仓库建议结构

```text
elder-companion-robot/
├── README.md
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── HARDWARE.md
│   ├── PROTOCOL.md
│   ├── DATABASE.md
│   └── ROADMAP.md
├── pi-backend/
│   ├── app/
│   ├── tests/
│   ├── scripts/
│   ├── requirements.txt
│   ├── .env.example
│   └── README.md
├── esp32-firmware/
│   ├── CMakeLists.txt
│   ├── main/
│   ├── components/
│   └── README.md
├── web-admin/
│   ├── README.md
│   └── src/
├── assets/
│   ├── faces/
│   ├── sounds/
│   └── icons/
└── tools/
    ├── serial_monitor.py
    ├── mock_esp32.py
    └── mock_audio.py
```

---

## 17. 第一阶段开发任务

### Phase 0：项目脚手架

目标：先把工程结构搭好。

任务：

1. 创建仓库目录；
2. 创建 `pi-backend`；
3. 创建 `esp32-firmware`；
4. 创建 `docs`；
5. 创建 `.env.example`；
6. 创建基础 README；
7. 定义串口协议；
8. 定义状态机枚举。

验收标准：

```text
仓库可以启动
后端服务可以运行
协议文档存在
状态机枚举存在
```

---

### Phase 1：树莓派后端最小闭环

目标：不依赖硬件，先跑通文字对话。

任务：

1. FastAPI 服务；
2. SQLite 数据库；
3. `/chat/text` 接口；
4. Mock LLM 客户端；
5. conversation_turns 数据表；
6. 保存用户输入和助手回复；
7. 返回机器人状态。

验收标准：

```text
curl 调用 /chat/text 可以得到回复
数据库中能看到对话记录
```

---

### Phase 2：ESP32 状态屏

目标：树莓派可以控制 ESP32 表情状态。

任务：

1. ESP32 显示开机动画；
2. 实现 `IDLE`；
3. 实现 `LISTENING`；
4. 实现 `THINKING`；
5. 实现 `SPEAKING`；
6. 通过 USB 串口接收 JSON Lines；
7. 心跳上报；
8. 按键事件上报。

验收标准：

```text
树莓派发送 {"type":"state","state":"LISTENING"}
ESP32 屏幕切换到聆听表情
```

---

### Phase 3：树莓派与 ESP32 联调

目标：按键触发一次完整的文字/模拟语音对话。

任务：

1. 树莓派串口服务；
2. 接收 `WAKE_BUTTON_PRESSED`；
3. 后端进入 `LISTENING`；
4. 使用 mock 文字代替 STT；
5. 调用 LLM；
6. 使用 mock TTS；
7. 通知 ESP32 显示 `SPEAKING`；
8. 完成后回到 `IDLE`。

验收标准：

```text
按 ESP32 按钮后
屏幕从 IDLE → LISTENING → THINKING → SPEAKING → IDLE
树莓派数据库保存一轮对话
```

---

### Phase 4：摄像头人脸识别

目标：树莓派能识别老人身份。

任务：

1. 摄像头采集；
2. 人脸检测；
3. 人脸注册；
4. 人脸匹配；
5. 识别结果绑定 user_id；
6. 未识别时进入访客模式；
7. 摄像头关闭时禁用识别。

验收标准：

```text
识别到已注册老人后
ESP32 显示欢迎表情
后端当前用户变成对应 user_id
```

---

### Phase 5：真实 STT / LLM / TTS

目标：接入外部 API。

任务：

1. 接入 STT；
2. 接入 LLM；
3. 接入 TTS；
4. 统一错误处理；
5. 超时处理；
6. 网络异常提示；
7. API Key 使用 `.env`；
8. 日志脱敏。

验收标准：

```text
用户说话后
机器人可以返回语音回复
ESP32 显示对应状态
```

---

### Phase 6：1.43C 板载音频接入

目标：使用 1.43C 自带麦克风和小喇叭。

任务：

1. ESP32 采集板载双麦克风；
2. ESP32 播放小喇叭；
3. 选择音频传输方案；
4. 实现音频上行；
5. 实现音频下行；
6. 处理播放时停止录音；
7. 调整音量；
8. 测试回声和啸叫。

验收标准：

```text
不使用外置 USB 麦克风和外置 USB 音箱
只使用 1.43C + 小喇叭
完成一次语音聊天
```

---

### Phase 7：长期记忆和自传草稿

目标：把聊天内容变成自传素材。

任务：

1. 每轮对话后提取记忆候选；
2. 保存 memory_facts；
3. 生成 daily_summary；
4. 生成待确认问题；
5. 人生事件入库；
6. 生成章节草稿；
7. 草稿显示在 Web 后台；
8. 支持人工修改和确认。

验收标准：

```text
一周的对话可以生成一段自传草稿
草稿中每个事实都能追溯来源
```

---

## 18. 后端 API 草案

### 18.1 健康检查

```http
GET /health
```

返回：

```json
{
  "status": "ok"
}
```

---

### 18.2 文本聊天

```http
POST /chat/text
```

请求：

```json
{
  "user_id": "user_001",
  "text": "我年轻的时候在纺织厂上班"
}
```

返回：

```json
{
  "reply": "听起来那是一段很重要的经历。您还记得那家纺织厂在哪个城市吗？",
  "state": "SPEAKING"
}
```

---

### 18.3 当前设备状态

```http
GET /device/state
```

返回：

```json
{
  "state": "IDLE",
  "mic_muted": false,
  "camera_blocked": false,
  "current_user_id": "user_001"
}
```

---

### 18.4 注册人脸

```http
POST /face/register
```

请求：

```json
{
  "user_id": "user_001",
  "display_name": "张奶奶"
}
```

返回：

```json
{
  "status": "ok",
  "face_profile_id": "face_001"
}
```

---

### 18.5 生成自传章节

```http
POST /biography/generate-chapter
```

请求：

```json
{
  "user_id": "user_001",
  "chapter_title": "我的工作岁月"
}
```

返回：

```json
{
  "chapter_id": "chapter_001",
  "status": "draft"
}
```

---

## 19. Codex 开发提示词

后续可以把下面这段给 Codex：

```text
请根据 docs/PROJECT_SPEC.md 构建项目第一阶段代码。

优先目标：
1. 创建 elder-companion-robot 仓库结构；
2. 实现 pi-backend 的 FastAPI 最小服务；
3. 实现 SQLite 数据库模型；
4. 实现 /health 和 /chat/text；
5. 实现 conversation_turns 持久化；
6. 创建 device state 状态机；
7. 创建 ESP32 通信协议的 Python 端解析和序列化；
8. 提供 mock_esp32.py，用于模拟 ESP32 发按钮事件和接收状态；
9. 所有 API Key 用 .env，不要写死；
10. 暂时使用 MockLLM，后续再替换为真实 API。

请保持代码模块化，补充 README 和最小测试。
```

---

## 20. 第一版最小可运行目标

不要一开始做完整产品。第一版最小目标是：

```text
1. 树莓派后端可以启动；
2. ESP32 可以显示表情；
3. 树莓派可以通过串口控制 ESP32 状态；
4. 按下按钮可以触发一次对话流程；
5. 对话内容可以保存；
6. 摄像头可以识别老人；
7. 自传模块可以根据几段文字生成草稿。
```

---

## 21. 当前重要决策汇总

1. 机器人本体使用微雪 ESP32-S3-Touch-AMOLED-1.43C；
2. 不再购买普通 1.43 作为主屏；
3. 1.43C 负责表情、触摸、麦克风采集、小喇叭播放；
4. 树莓派放在底座里，作为中转站和本地服务器；
5. 摄像头装在机器人正面，只做人脸识别；
6. 人脸识别在树莓派上处理；
7. LLM、STT、TTS 都由树莓派调用外部 API；
8. 对话、自传、长期记忆都保存在树莓派 SSD；
9. ESP32 不保存老人隐私数据；
10. 第一版可以用 mock 音频先跑通逻辑，再接 1.43C 板载音频。

---

## 22. 待确认问题

后续开发前还需要确认：

1. 树莓派系统使用 Raspberry Pi OS 还是 Ubuntu Server；
2. 后端语言是否确定为 Python；
3. ESP32 固件是否确定使用 ESP-IDF；
4. 音频传输最终选择 USB Audio Class 还是自定义音频流；
5. 摄像头使用 USB 小摄像头还是 Raspberry Pi Camera Module；
6. 外壳是否采用 3D 打印；
7. 是否需要家属手机端后台；
8. 是否需要支持多位老人；
9. 是否需要离线模式；
10. 是否需要保存原始音频，默认建议不保存。

---

## 23. 当前推荐的下一步

建议现在让 Codex 先做：

```text
Phase 0 + Phase 1 + Phase 2 的软件骨架
```

也就是：

```text
树莓派后端
+
数据库
+
状态机
+
ESP32 通信协议
+
mock ESP32
```

不要先让 Codex 直接做：

```text
完整音频链路
完整人脸识别
完整自传系统
完整 Web 后台
```

因为这些可以在骨架稳定后逐步接入。

