# Windows 开发环境配置

本文档面向 Windows 10/11、PowerShell 和当前“老人陪伴对话机器人”仓库，包含两套可独立使用的环境：

- Python 后端与无硬件模拟环境；
- ESP32-S3 固件编译、烧录和串口监视环境。

只调试后端时不需安装 ESP-IDF。需要编译或烧录 AMOLED 开发板时，再完成第六节。

## 1. 环境要求

建议使用：

- Windows 10 64 位或 Windows 11 64 位；
- PowerShell 5.1 或更高版本；
- Git for Windows；
- Python 3.11 或更高版本；
- ESP-IDF 5.5.x，开发板联调时建议使用 5.5.3。

ESP-IDF 对 Windows 路径较敏感。仓库和 ESP-IDF 均应放在较短、无空格、不含中文的路径下。本文统一使用：

```text
C:\work\elderly-conversation-robot
```

不要放在下列位置：

```text
C:\Users\中文用户名\Desktop\老年人对话机器人
C:\Program Files\...
```

## 2. 安装 Git 和 Python

### 2.1 Git for Windows

从 [Git for Windows 官网](https://git-scm.com/download/win) 下载并安装。安装时保持默认选项即可，但要确保 Git 可以从命令行使用。

重新打开 PowerShell，检查：

```powershell
git --version
```

配置提交身份：

```powershell
git config --global user.name "胡宇博"
git config --global user.email "1300856452@qq.com"
git config --global core.longpaths true
```

### 2.2 Python

从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/) 安装 Python 3.11 或更高版本。安装器中建议启用 Python Launcher；如果显示 `Add Python to PATH`，也建议勾选。

检查 Python：

```powershell
py -3 --version
```

输出应为 `Python 3.11.x` 或更高版本。

## 3. 获取私有仓库

在 PowerShell 中执行：

```powershell
New-Item -ItemType Directory -Path C:\work -Force
Set-Location C:\work
git clone https://github.com/shdgxyen/elderly-conversation-robot.git
Set-Location .\elderly-conversation-robot
```

这是私有仓库。Git for Windows 通常会在首次 HTTPS 操作时通过浏览器请求 GitHub 授权。如果当前 Windows 账号尚未授权，按浏览器提示登录 GitHub 账号 `shdgxyen`。

检查当前分支和远程地址：

```powershell
git status -sb
git remote -v
```

## 4. 配置 Python 后端

以下命令都从仓库根目录 `C:\work\elderly-conversation-robot` 执行。

### 4.1 创建虚拟环境

```powershell
py -3 -m venv .\pi-backend\.venv
.\pi-backend\.venv\Scripts\python.exe -m pip install --upgrade pip
.\pi-backend\.venv\Scripts\python.exe -m pip install -r .\pi-backend\requirements.txt
Copy-Item .\pi-backend\.env.example .\pi-backend\.env
```

文档中直接调用虚拟环境内的 `python.exe`，因此无需激活虚拟环境，也不会受 PowerShell 脚本执行策略影响。

如果希望手动激活，可以执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\pi-backend\.venv\Scripts\Activate.ps1
```

`RemoteSigned` 只对当前 Windows 用户生效。如果电脑受学校或公司组策略管理，不要绕过管理员策略，直接使用前面的完整 `python.exe` 路径即可。参见 [Microsoft PowerShell 执行策略文档](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_execution_policies)。

### 4.2 启动后端

```powershell
Set-Location .\pi-backend
.\.venv\Scripts\python.exe -m app
```

启动成功后：

- API 地址：<http://127.0.0.1:8000>
- Swagger 交互文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

新开一个 PowerShell 窗口检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

测试一次文本对话：

```powershell
$body = @{
    user_id = "demo-user"
    display_name = "张奶奶"
    text = "今天天气真好"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8000/chat/text `
    -ContentType "application/json; charset=utf-8" `
    -Body $body
```

按 `Ctrl+C` 停止服务。

### 4.3 运行测试

```powershell
Set-Location C:\work\elderly-conversation-robot\pi-backend
.\.venv\Scripts\python.exe -m pytest -q
```

## 5. 无硬件联调

使用两个 PowerShell 窗口。

### 5.1 配置 TCP 模拟设备

编辑 `pi-backend\.env`，将设备配置改为：

```dotenv
ELDER_ROBOT_DEVICE_TRANSPORT=mock_tcp
ELDER_ROBOT_DEVICE_MOCK_TCP_HOST=127.0.0.1
ELDER_ROBOT_DEVICE_MOCK_TCP_PORT=8765
```

### 5.2 启动 ESP32 模拟器

窗口 A：

```powershell
Set-Location C:\work\elderly-conversation-robot
.\pi-backend\.venv\Scripts\python.exe .\tools\mock_esp32.py
```

模拟器默认监听 `127.0.0.1:8765`。可以在其交互终端输入 `wake`、`stop`、`status` 等命令。

### 5.3 启动后端

窗口 B：

```powershell
Set-Location C:\work\elderly-conversation-robot\pi-backend
.\.venv\Scripts\python.exe -m app
```

后端与模拟器建立连接后，调用 `/chat/text` 即可观察设备状态变化。

## 6. 配置 ESP-IDF 5.5.3

### 6.1 安装工具链

使用乐鑫官方的 [ESP-IDF Tools Installer for Windows](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32s3/get-started/windows-setup-scratch.html)。安装时选择 ESP-IDF 5.5.3。该安装器会配置固件编译所需的 Python、Git、CMake、Ninja、OpenOCD 和交叉编译器。

安装路径应尽量短且只包含 ASCII 字符，例如：

```text
C:\Espressif
```

安装完成后，从开始菜单打开安装器创建的 `ESP-IDF 5.5 PowerShell` 快捷方式。普通 PowerShell 不会自动加载 ESP-IDF 环境。

检查：

```powershell
idf.py --version
```

输出应显示 ESP-IDF 5.5.x。

### 6.2 编译固件

仍在 `ESP-IDF 5.5 PowerShell` 中执行：

```powershell
Set-Location C:\work\elderly-conversation-robot\esp32-firmware
idf.py set-target esp32s3
idf.py build
```

首次编译会下载受管组件，包括 Waveshare AMOLED BSP、LVGL 和 QMI8658 IMU 驱动，因此需要联网，而且用时会明显长于后续编译。

当前默认配置针对 `ESP32-S3-Touch-AMOLED-1.8`。需要查看或调整配置时：

```powershell
idf.py menuconfig
```

项目配置位于：

```text
Component config
└─ Elder companion firmware
```

### 6.3 识别串口

将开发板通过可传输数据的 USB 线连接电脑，然后执行：

```powershell
[System.IO.Ports.SerialPort]::GetPortNames()
```

也可以打开“设备管理器 -> 端口 (COM 和 LPT)”查看。本文假设设备是 `COM5`。

### 6.4 烧录和查看日志

```powershell
idf.py -p COM5 flash monitor
```

退出监视器按 `Ctrl+]`。

首次烧录、分区表变更或设备仍显示厂家 Demo 时，可先擦除 Flash：

```powershell
idf.py -p COM5 erase-flash
idf.py -p COM5 flash monitor
```

烧录完成后，可在日志中查找：

```text
AMOLED 1.8 face UI ready
IMU motion task started
```

IMU 眼神方向和摇晃触发阈值仍需根据实际板卡进行标定。

## 7. 连接真实 ESP32 与后端

先退出 `idf.py monitor`，避免串口被占用。在 `pi-backend\.env` 中配置：

```dotenv
ELDER_ROBOT_DEVICE_TRANSPORT=serial
ELDER_ROBOT_DEVICE_SERIAL_PORT=COM5
ELDER_ROBOT_DEVICE_SERIAL_BAUDRATE=115200
```

启动后端：

```powershell
Set-Location C:\work\elderly-conversation-robot\pi-backend
.\.venv\Scripts\python.exe -m app
```

同一个 COM 端口不能同时被 ESP-IDF Monitor、后端、串口助手或其他程序打开。

## 8. Windows 与本项目的差异

仓库根目录的 `Makefile` 使用了 Unix 风格的路径和命令，例如：

```text
.venv/bin/python
touch
cp
```

因此不要在原生 PowerShell 中直接执行 `make setup`、`make run` 或 `make test`。请使用本文档提供的 PowerShell 等价命令。

WSL2 可用于运行 Python 后端，但 ESP32 USB 烧录涉及 USB 设备转发，配置更复杂。本项目在 Windows 上建议使用原生 ESP-IDF PowerShell。

## 9. 常见问题

### `python` 或 `py` 不是命令

1. 关闭所有 PowerShell 窗口并重新打开。
2. 确认 Python 已安装且 Python Launcher 已启用。
3. 在 Windows 设置中检查“应用执行别名”，避免 Microsoft Store 别名拦截 `python.exe`。

### 无法运行 `Activate.ps1`

可以不激活虚拟环境，直接使用：

```powershell
.\pi-backend\.venv\Scripts\python.exe
```

或者仅为当前用户设置 `RemoteSigned`：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### `idf.py` 不是命令

当前打开的是普通 PowerShell。关闭该窗口，改为从开始菜单打开 `ESP-IDF 5.5 PowerShell`。

### CMake、Ninja 或 Python 报路径错误

将仓库移到类似 `C:\work\elderly-conversation-robot` 的短 ASCII 路径，不要在中文用户桌面、OneDrive 同步目录或带空格的目录中编译。

### 首次 `idf.py build` 长时间无输出

首次构建需要下载多个受管组件。先等待下载完成；如果网络中断，重新执行 `idf.py build`，已下载内容通常会复用缓存。

### 找不到 COM 端口

1. 确认 USB 线支持数据传输，而不是只能充电。
2. 更换 USB 接口并重新插拔开发板。
3. 查看 Windows 设备管理器中是否有黄色感叹号。
4. 确认 ESP-IDF Monitor、串口助手和后端没有占用端口。

### 数据库或本地配置不应提交

项目的 `.gitignore` 已忽略 `.env`、`.venv`、SQLite 数据库、构建目录和运行日志。提交前仍应执行：

```powershell
git status --short
```

不要将 API Key、GitHub Token、真实老人信息、对话数据库、原始音频或视频提交到仓库。

## 10. 环境验收清单

后端环境：

- `git --version` 正常输出；
- `py -3 --version` 为 Python 3.11 或更高版本；
- 虚拟环境位于 `pi-backend\.venv`；
- `python -m app` 可启动 FastAPI；
- `/health` 返回成功；
- `pytest -q` 通过。

ESP32 环境：

- 仓库位于短 ASCII 路径；
- `idf.py --version` 显示 5.5.x；
- `idf.py set-target esp32s3` 成功；
- `idf.py build` 显示 `Project build complete`；
- Windows 能识别开发板 COM 端口；
- `idf.py -p COMx flash monitor` 可烧录并显示启动日志。

## 11. 官方参考

- [Python on Windows](https://docs.python.org/3/using/windows.html)
- [Git for Windows](https://git-scm.com/download/win)
- [PowerShell execution policies](https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_execution_policies)
- [ESP-IDF 5.5.3 Windows 工具链安装](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32s3/get-started/windows-setup-scratch.html)
- [Waveshare ESP32-S3-Touch-AMOLED-1.43C](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.43C/Development-Environment-Setup-ESP-IDF)

