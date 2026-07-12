# SQLite 数据库设计

第一阶段使用 SQLAlchemy 2 管理 SQLite。数据库路径由环境变量配置，默认写入 Raspberry Pi 本地数据目录，不应提交到版本库。

## 表

| 表 | 用途 | 关键关系 |
|---|---|---|
| `users` | 老人基本信息和称呼 | 其他用户数据的父记录 |
| `face_profiles` | 本地人脸向量文件引用 | `user_id → users.id` |
| `conversation_turns` | 每一条用户或助手消息 | `user_id → users.id` |
| `daily_summaries` | 每日对话摘要 | `user_id → users.id` |
| `memory_facts` | 可追溯长期记忆 | `user_id → users.id` |
| `life_events` | 已整理的人生事件 | `user_id → users.id` |
| `autobiography_chapters` | 自传章节草稿和审核状态 | `user_id → users.id` |

JSON 列只保存 ID 列表或结构化候选，不保存原始音频、视频或 API 密钥。时间在 SQLite 中规范化为 UTC，ORM 读取时会恢复 `UTC` 时区信息，展示时再转成本地时区。

## 对话写入一致性

一次 `/chat/text` 调用在同一数据库事务中写入用户消息和助手回复。模型生成失败时事务回滚，避免出现只有半轮对话的记录。`should_remember=false` 的对话可以继续用于即时回复，但不得进入长期记忆提取流程。

## 隐私

- 默认只保存文本，不保存原始音频；
- `privacy_level` 限定为 `private`、`family`、`public`；
- 人脸表只保存本地 embedding 文件路径，不保存摄像头录像；
- SQLite 文件、WAL 文件和运行数据目录均在 `.gitignore` 中；
- 正式部署需限制数据目录权限并制定备份/删除策略。

第一阶段直接由应用启动时建表。进入需要生产数据保留的阶段前，应引入 Alembic 版本化迁移。
