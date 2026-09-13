#!/usr/bin/env python3
"""1.43C 圆屏终端实机检查：表情、表情轮播和喇叭测试。

通过 USB Serial/JTAG 上的 JSON Lines 通道与固件通信，依赖 pyserial（make setup 已安装）：

    pi-backend/.venv/bin/python tools/device_check.py                       逐个发送表情并确认
    pi-backend/.venv/bin/python tools/device_check.py --auto --hold 8       自动轮播
    pi-backend/.venv/bin/python tools/device_check.py --demo                让设备自己循环展示全部表情
    pi-backend/.venv/bin/python tools/device_check.py --sound speaker_test  播放内置喇叭测试音
    pi-backend/.venv/bin/python tools/device_check.py --watch 30 -v         只监听设备输出

使用前请关闭 Arduino IDE 串口监视器等占用串口的程序。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import threading
import time

import serial

FACES = [
    ("happy", "开心", "眯眼笑：眼睛和嘴一起轻快上下弹跳，嘴角一张一合地咧开，偶尔眨眼"),
    ("sad", "难过", "眼睛和下弯嘴缓慢下沉再回来（叹气），左眼下方一滴蓝色眼泪反复落下"),
    ("surprised", "惊讶", "先小后大的两段式惊讶动画（约 2.3 秒）；自动轮播时每 2.6 秒重播一次"),
    ("confused", "疑惑", "一大一小的眼睛左右张望，平嘴反向移动，下方问号上下跳动"),
    ("comfort", "安慰", "暖色细笑眼和微笑缓慢起伏，两侧彩色光点向上飘散，偶尔眨眼"),
    ("wink", "眨眼", "右眼快速闭上再弹开，约 2 秒一次，嘴角咧笑"),
    ("sleepy", "犯困", "眼皮缓慢耷拉又抬起，右上方飘出小 z 并淡出"),
]
AUDIO_DONE_STAGE = "playback_completed"
AUDIO_SETTLE_S = 3.0  # playback_completed 之后 COMFORT 保持 900 ms 再回到 IDLE
SURPRISE_REPLAY_S = 2.6  # 惊讶动画 2.3 秒后自行回到待机，轮播时稍后重播
SPEAKER_TEST_END_STAGES = ("speaker_test_completed", "cycle_failed")


class Device:
    def __init__(self, port: str, verbose: bool) -> None:
        self.verbose = verbose
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 115200
        self.ser.timeout = 0.2
        # 保持 pyserial 默认的 DTR/RTS=True：系统打开串口时两条线同时拉高，板子不受影响。
        # 若分两步拉低 DTR、RTS，正好构成 ESP32-S3 USB 复位时序，会把板子重启。
        self.ser.dtr = True
        self.ser.rts = True
        self.ser.open()
        self.write_lock = threading.Lock()
        self.running = True
        self.json_lines = 0
        self.heartbeats = 0
        self.audio_stages: list[tuple[str, int]] = []
        self.last_audio_at = 0.0
        self.audio_done_at = 0.0
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        buf = b""
        while self.running:
            try:
                buf += self.ser.read(1024)
            except serial.SerialException as exc:
                print(f"\n[串口] 读取失败：{exc}")
                self.running = False
                return
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self._handle(raw.decode("utf-8", errors="replace").strip())

    def _handle(self, line: str) -> None:
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(f"  [设备·非JSON] {line}")
            return
        self.json_lines += 1
        kind = msg.get("type")
        if kind == "heartbeat":
            self.heartbeats += 1
            if self.verbose:
                print(f"  [心跳] uptime={msg.get('uptime_ms', 0) / 1000:.1f}s")
        elif kind == "audio_status":
            stage, code = msg.get("stage", "?"), msg.get("code", 0)
            self.audio_stages.append((stage, code))
            self.last_audio_at = time.monotonic()
            if stage == AUDIO_DONE_STAGE:
                self.audio_done_at = self.last_audio_at
            print(f"  [音频] {stage} {'✓' if code == 0 else f'✗ code={code}'}")
        elif kind == "audio_quality":
            print(
                f"  [录音质量] 选用麦克风 {msg.get('selected_mic')}，"
                f"SNR 指标 {msg.get('snr_x100', 0) / 100:.2f}，"
                f"数字增益 {msg.get('gain_x100', 0) / 100:.2f}x，削波 {msg.get('clip')}"
            )
        else:
            print(f"  [设备] {line}")

    def send(self, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.write_lock:
            self.ser.write(data.encode("utf-8"))
            self.ser.flush()

    def close(self) -> None:
        self.running = False
        self.reader.join(timeout=1)
        self.ser.close()


def find_port() -> str | None:
    for pattern in ("/dev/cu.usbmodem*", "/dev/ttyACM*"):
        ports = sorted(glob.glob(pattern))
        if ports:
            return ports[0]
    return None


def open_device(port: str, verbose: bool, timeout: float = 10.0) -> Device:
    deadline = time.monotonic() + timeout
    while True:
        try:
            return Device(port, verbose)
        except serial.SerialException as exc:
            if time.monotonic() > deadline:
                raise SystemExit(f"无法打开 {port}：{exc}\n请确认 Arduino IDE 等串口监视器已关闭。")
            time.sleep(0.5)


def wait_until(dev: Device, condition, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end and dev.running:
        if condition():
            return True
        time.sleep(0.2)
    return condition()


def wait_for_boot_test(dev: Device, limit: float) -> None:
    """开机录音自检会切换 LISTENING/SPEAKING/COMFORT/IDLE，等它结束再发表情。"""
    start = time.monotonic()
    print(f"等待开机自检结束（最多 {limit:.0f} 秒，期间请勿按 BOOT 键）…")
    while time.monotonic() - start < limit and dev.running:
        now = time.monotonic()
        if dev.audio_done_at and now - dev.last_audio_at > AUDIO_SETTLE_S:
            print("开机录音自检已结束。")
            return
        if dev.audio_stages and dev.audio_stages[-1][1] != 0 and now - dev.last_audio_at > AUDIO_SETTLE_S:
            print("音频自检报告了错误（见上方），继续做表情检查。")
            return
        if not dev.audio_stages and dev.heartbeats and now - start > 8.0:
            print("没有正在进行的录音自检，直接开始。")
            return
        time.sleep(0.2)
    print("等待超时，继续做表情检查。")


def hold_face(dev: Device, command: dict, hold: float) -> None:
    """自动模式下保持一个表情；惊讶动画会自己结束，所以定期重播。"""
    end = time.monotonic() + hold
    while dev.running:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        if command["emotion"] == "surprised" and remaining > SURPRISE_REPLAY_S:
            time.sleep(SURPRISE_REPLAY_S)
            dev.send(command)
        else:
            time.sleep(remaining)


def run_faces(dev: Device, auto: bool, hold: float, rounds: int) -> list[tuple[str, str, bool | None, str]]:
    interactive = not auto and sys.stdin.isatty()
    total_rounds = 1 if interactive else max(rounds, 1)
    results = []
    for round_index in range(total_rounds):
        if total_rounds > 1:
            print(f"\n—— 第 {round_index + 1}/{total_rounds} 轮 ——")
        for i, (emotion, name, look) in enumerate(FACES, 1):
            print(f"\n[{i}/{len(FACES)}] {name}（{emotion}）—— 应看到：{look}")
            command = {"type": "face", "emotion": emotion, "intensity": 1.0}
            dev.send(command)
            if interactive:
                answer = input("  显示正确吗？[回车=正确 / 输入问题描述=不对]: ").strip()
                ok = answer.lower() in ("", "y", "yes", "对", "是")
                results.append((name, emotion, ok, "" if ok or answer.lower() == "n" else answer))
            else:
                hold_face(dev, command, hold)
                if round_index == total_rounds - 1:
                    results.append((name, emotion, None, ""))
    dev.send({"type": "state", "state": "IDLE"})
    return results


def play_sound(dev: Device, name: str, timeout: float) -> None:
    if not wait_until(dev, lambda: dev.json_lines > 0, 15.0):
        print("15 秒内没有收到设备数据，仍尝试发送。")
    dev.send({"type": "sound", "name": name})
    if name != "speaker_test":
        print(f"已发送 sound={name}（固件目前只实现 speaker_test）。")
        time.sleep(1.0)
        return
    print("已请求喇叭测试音（约 14 秒；若开机录音自检未结束，会排在它之后）…")
    first = len(dev.audio_stages)
    finished = wait_until(
        dev, lambda: any(s in SPEAKER_TEST_END_STAGES for s, _ in dev.audio_stages[first:]), timeout)
    stages = [s for s, _ in dev.audio_stages[first:]]
    if "speaker_test_completed" in stages:
        print("✓ 喇叭测试音播放完成。")
    elif finished:
        print("✗ 播放失败，见上方音频阶段。")
    else:
        print(f"✗ {timeout:.0f} 秒内未完成。")


def summary(dev: Device, results: list) -> None:
    if results:
        print("\n==== 表情检查结果 ====")
        for name, emotion, ok, note in results:
            status = {True: "✓ 正确", False: "✗ 不对", None: "· 待目视确认"}[ok]
            print(f"  {name}  {emotion:<10} {status}  {note}")
    errors = [s for s, c in dev.audio_stages if c != 0]
    print(f"\n心跳 {dev.heartbeats} 次；音频阶段 {len(dev.audio_stages)} 条，其中错误 {len(errors)} 条 {errors or ''}")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description="1.43C 圆屏终端实机检查")
    ap.add_argument("--port", help="默认自动选择 /dev/cu.usbmodem* 或 /dev/ttyACM*（Windows 需指定 COMx）")
    ap.add_argument("--auto", action="store_true", help="自动轮播，不逐个确认")
    ap.add_argument("--hold", type=float, default=6.0, help="自动模式下每个表情停留秒数")
    ap.add_argument("--rounds", type=int, default=1, help="自动模式轮播几轮")
    ap.add_argument("--demo", action="store_true", help="让设备自己循环播放全部表情后退出")
    ap.add_argument("--sound", metavar="NAME", help="播放声音，目前支持 speaker_test")
    ap.add_argument("--sound-timeout", type=float, default=60.0)
    ap.add_argument("--watch", type=float, default=0.0, help="只监听设备输出 N 秒")
    ap.add_argument("--no-wait", action="store_true", help="不等待开机录音自检")
    ap.add_argument("--boot-wait", type=float, default=45.0)
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每次心跳")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        raise SystemExit("没有找到 USB 串口设备，请检查连接或用 --port 指定。")
    print(f"串口：{port}")
    dev = open_device(port, args.verbose)
    results: list = []
    try:
        if args.sound:
            play_sound(dev, args.sound, args.sound_timeout)
        elif args.demo:
            dev.send({"type": "face", "emotion": "demo"})
            time.sleep(0.3)
            print("已启动设备端表情轮播；发送任意其他表情指令即可结束。")
        elif args.watch:
            print(f"监听设备输出 {args.watch:.0f} 秒…")
            wait_until(dev, lambda: False, args.watch)
        else:
            if not args.no_wait:
                wait_for_boot_test(dev, args.boot_wait)
            results = run_faces(dev, args.auto, args.hold, args.rounds)
    except KeyboardInterrupt:
        print("\n已中断。")
    finally:
        summary(dev, results)
        dev.close()


if __name__ == "__main__":
    main()
