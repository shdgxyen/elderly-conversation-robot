# ESP32-S3-Touch-AMOLED-1.8 表情屏联调记录

> 日期：2026-07-12
> 结果：表情 UI 预开发成功——1.8 寸方屏上以圆形画布渲染 15 个状态的表情，协议驱动切换正常。
> 本记录同时是讲义第八章的实战素材：每个坑都对应一个可讲的知识点。

---

## 一、做了什么

在 1.43C 圆屏到货前，用手头的 ESP32-S3-Touch-AMOLED-1.8（368×448 方屏）完成表情 UI 预开发。

新增/修改的文件：

| 文件 | 内容 |
|---|---|
| `main/ui/ui_board_amoled18.c` | 表情适配层：实现 `ui_board_*` 全部强符号，15 个状态的表情（眨眼、扫视、说话嘴型、思考省略号、隐私/网络图标），中文名用 LVGL 内置 CJK 字体 |
| `main/idf_component.yml` | 引入微雪官方托管 BSP（`waveshare/esp32_s3_touch_amoled_1_8`），屏幕引脚全部由 BSP 管理，仓库仍不硬编码 GPIO |
| `main/Kconfig.projbuild` | 新增 `ELDER_UI_BOARD_AMOLED18` 开关（默认开） |
| `main/CMakeLists.txt` | 按开关二选一编译桩或适配层（见坑 6） |
| `sdkconfig.defaults` | 16MB Flash、八线 PSRAM、自定义分区表、LVGL 字体配置 |
| `partitions.csv` | 8MB factory 分区（LVGL 应用超过默认 1MB） |

设计要点：所有表情坐标按**圆形画布直径的百分比**计算（画布 = min(宽,高)），换 466×466 的 1.43C 时表情代码零改动。

## 二、标准工作流（验证通过）

```bash
# 每个新终端先加载环境
. ~/esp/esp-idf/export.sh

# 同步代码（仓库路径含中文，必须拷到纯英文路径编译）
rm -rf ~/esp/elder-fw
cp -r "<仓库路径>/esp32-firmware" ~/esp/elder-fw
cd ~/esp/elder-fw

# 配置、编译、烧录
idf.py set-target esp32s3
idf.py build                                   # 成功标志：Project build complete
idf.py -p /dev/cu.usbmodemXXXX erase-flash     # 首次建议擦掉出厂 demo
idf.py -p /dev/cu.usbmodemXXXX flash monitor   # 成功标志：ui_amoled18: AMOLED 1.8 face UI ready
```

表情测试（先 `Ctrl+]` 退出 monitor，串口独占）：

```bash
printf '{"type":"state","state":"LISTENING"}\n' > /dev/cu.usbmodemXXXX
printf '{"type":"state","state":"SPEAKING"}\n'  > /dev/cu.usbmodemXXXX
printf '{"type":"user","recognized":true,"display_name":"张奶奶"}\n' > /dev/cu.usbmodemXXXX
printf '{"type":"state","state":"IDLE"}\n'      > /dev/cu.usbmodemXXXX
```

后端整机联调：`pi-backend/.env` 设 `ELDER_ROBOT_DEVICE_TRANSPORT=serial`、`ELDER_ROBOT_DEVICE_SERIAL_PORT=/dev/cu.usbmodemXXXX`，`make run` 后 curl `/chat/text`，表情随后端状态机自动切换。

## 三、踩坑记录（按时间顺序）

**坑 1：macOS Python 证书缺失。** `install.sh` 因 SSL 报错。python.org 安装的 Python 不带根证书。解决：运行 `/Applications/Python 3.14/Install Certificates.command` 后重装。

**坑 2：macOS 上 ESP-IDF 不自动安装 cmake/ninja。** 报 `"cmake" must be available on the PATH`。解决：`python3 tools/idf_tools.py install cmake ninja` 再重新 `. export.sh`（不必装 Homebrew）。

**坑 3：GitHub 子模块拉取中断。** mbedtls 等克隆 early EOF。解决：循环重试 `git submodule update --init --recursive`（git 每次重试有进展）；备选方案是 jihulab 国内镜像整体重克隆。

**坑 4：LVGL 托管组件下载假死。** 卡在 `NOTICE: [11/13] lvgl/lvgl`。注意：乐鑫组件仓库**没有** `components.espressif.cn` API 镜像（设置它会直接报连不上）；大文件下载本来就会自动走国内 CDN。解决：不设任何镜像变量，中断后重试 `idf.py build`，已下载组件有缓存。

**坑 5：build 目录残缺。** 报 `ninja: error: loading 'build.ninja'`。此前失败的 configure 留下空壳 build 目录，后续命令直接跳过配置。解决：`rm -rf build` 后重新 `idf.py build`。教训：**必须亲眼看到 `Project build complete` 才算编译成功**，否则烧的是旧固件。

**坑 6：弱符号桩压住了强符号实现（本次最核心的坑）。** 现象：心跳正常、`CONFIG_ELDER_UI_BOARD_AMOLED18=y`、组件齐全，但屏幕不亮，日志显示 `no display BSP linked`。原因：`ui_board_stub.c`（weak）与 `ui_board_amoled18.c`（strong）在同一静态库里，链接器用先取到的桩对象满足了引用，永远不会再拉取适配层对象。解决：CMakeLists 里按 Kconfig **二选一**编译，不让两个实现共存。教学点：*"程序在跑"和"每个模块都被链接进程序"是两回事。*

**坑 7：AMOLED 残影迷惑判断。** 换固件后屏幕仍显示出厂菜单——因为 AMOLED 面板有自己的显存，USB 不断电就一直显示最后画入的内容，与主控当前跑什么固件无关。断电重插即清空。教学点：判断屏幕状态要看"谁初始化了面板"，不能只看"屏幕上有没有东西"。

## 四、下一步

1. 后端串口整机联调（本记录第二节最后一段），即 Phase 3 预演；
2. 接入真实 LLM/STT/TTS（选型：阿里云百炼一站式，方言场景 STT 换讯飞；人脸识别按隐私规则本地跑，不用云 API）；
3. 1.43C 到货后：换 BSP 依赖与面板初始化，表情代码不动。
