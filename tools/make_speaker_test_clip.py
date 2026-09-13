#!/usr/bin/env python3
"""生成固件内置的喇叭测试音（16 kHz、单声道、PCM16 小端）。

依赖 macOS 自带的 say（中文语音）与 afconvert，仅在需要重新生成时运行：

    python3 tools/make_speaker_test_clip.py

内容依次为：中文提示语、上行音阶、150 Hz–6 kHz 对数扫频、结束语。
提示语判断语音清晰度，音阶听音色，扫频暴露破音、共振和高低频缺失。
"""

from __future__ import annotations

import argparse
import array
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

RATE = 16000
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "esp32-firmware/main/audio/speaker_test.pcm"
VOICES = ("Flo (中文（中国大陆）)", "Reed (中文（中国大陆）)", "Tingting", "Meijia")
INTRO = "您好，我是陪伴机器人。现在开始喇叭测试。"
OUTRO = "测试结束。声音清楚吗？"


def dbfs(db: float) -> float:
    return 32767 * 10 ** (db / 20)


def speak(text: str, workdir: Path, name: str) -> list[float]:
    aiff, wav = workdir / f"{name}.aiff", workdir / f"{name}.wav"
    for voice in VOICES:
        result = subprocess.run(["say", "-v", voice, "-r", "175", "-o", str(aiff), text],
                                capture_output=True)
        if result.returncode == 0 and aiff.exists() and aiff.stat().st_size > 4096:
            break
    else:
        raise SystemExit("找不到可用的中文语音，请在“系统设置 > 辅助功能 > 朗读内容”中下载。")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1",
                    str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        samples = array.array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    gain = dbfs(-3) / (max((abs(s) for s in samples), default=1) or 1)
    print(f"  语音「{text}」：{voice}，{len(samples) / RATE:.1f} s")
    return [s * gain for s in samples]


def silence(ms: int) -> list[float]:
    return [0.0] * (RATE * ms // 1000)


def chime(freq: float, ms: int, level_db: float) -> list[float]:
    """钟声式音符：基频加柔和的八度泛音，快起音、指数衰减，结尾无爆音。"""
    n, amp, attack = RATE * ms // 1000, dbfs(level_db), RATE * 0.008
    out = []
    for i in range(n):
        t = i / RATE
        env = min(1.0, i / attack) * math.exp(-3.2 * t / (ms / 1000))
        out.append(amp * env * (math.sin(2 * math.pi * freq * t)
                                + 0.3 * math.sin(4 * math.pi * freq * t)) / 1.3)
    return out


def sweep(start_hz: float, end_hz: float, ms: int, level_db: float) -> list[float]:
    n, amp, fade = RATE * ms // 1000, dbfs(level_db), RATE * 0.05
    ratio, phase, out = math.log(end_hz / start_hz), 0.0, []
    for i in range(n):
        phase += 2 * math.pi * start_hz * math.exp(ratio * i / n) / RATE
        out.append(amp * min(1.0, i / fade, (n - i) / fade) * math.sin(phase))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="生成固件内置的喇叭测试音")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        intro = speak(INTRO, Path(tmp), "intro")
        outro = speak(OUTRO, Path(tmp), "outro")

    scale: list[float] = []
    for freq in (523.25, 659.25, 783.99, 1046.5):  # C5 E5 G5 C6
        scale += chime(freq, 280, -6)
    scale += chime(1046.5, 700, -6)

    clip = (intro + silence(400) + scale + silence(400)
            + sweep(150, 6000, 3000, -12) + silence(350) + outro + silence(200))
    pcm = array.array("h", (max(-32768, min(32767, round(v))) for v in clip))
    if sys.byteorder != "little":
        pcm.byteswap()
    args.output.write_bytes(pcm.tobytes())
    print(f"✓ {args.output}：{len(pcm) / RATE:.1f} s，{len(pcm) * 2 // 1024} KB")


if __name__ == "__main__":
    main()
