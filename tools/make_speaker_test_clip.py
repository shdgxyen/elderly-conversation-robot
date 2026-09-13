#!/usr/bin/env python3
"""生成固件内置的喇叭测试音（16 kHz、单声道、PCM16 小端）。

依赖 macOS 自带的 say（中文语音）与 afconvert，仅在需要重新生成时运行：

    python3 tools/make_speaker_test_clip.py

内容依次为：中文提示语、上行音阶、150 Hz–6 kHz 对数扫频、结束语。
提示语判断语音清晰度，音阶听音色，扫频暴露破音、共振和高低频缺失。

板载小喇叭放不出人声低频，直接播放合成语音会发闷、发糊，所以提示语按喇叭做了
处理：300 Hz 四阶高通、3 kHz 附近 +5 dB 清晰度提升、3:1 压缩，峰值留 6 dB
余量避免功放过载。这组参数是在 1.43C 实机上对比几种处理后选出的。
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
# 按清晰度排序：Tingting 是 macOS 自带普通话语音里在小喇叭上最清楚的。
VOICES = ("Tingting", "Meijia", "Flo (中文（中国大陆）)", "Reed (中文（中国大陆）)")
SPEECH_RATE_WPM = 170
INTRO = "您好，我是陪伴机器人。现在开始喇叭测试。"
OUTRO = "测试结束。声音清楚吗？"


def dbfs(db: float) -> float:
    return 32767 * 10 ** (db / 20)


def synthesize(text: str, workdir: Path, name: str) -> list[float]:
    aiff, wav = workdir / f"{name}.aiff", workdir / f"{name}.wav"
    for voice in VOICES:
        result = subprocess.run(
            ["say", "-v", voice, "-r", str(SPEECH_RATE_WPM), "-o", str(aiff), text],
            capture_output=True)
        if result.returncode == 0 and aiff.exists() and aiff.stat().st_size > 4096:
            break
    else:
        raise SystemExit("找不到可用的中文语音，请在“系统设置 > 辅助功能 > 朗读内容”中下载 Tingting。")
    convert = ["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1"]
    high_quality = convert + ["--src-complexity", "bats", "--src-quality", "127"]
    if subprocess.run(high_quality + [str(aiff), str(wav)], capture_output=True).returncode != 0:
        subprocess.run(convert + [str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        samples = array.array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    print(f"  语音「{text}」：{voice}，{len(samples) / RATE:.1f} s")
    return [float(s) for s in samples]


def biquad(x: list[float], b0: float, b1: float, b2: float,
           a0: float, a1: float, a2: float) -> list[float]:
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for s in x:
        y = b0 * s + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, s, y1, y
        out.append(y)
    return out


def highpass(x: list[float], freq: float, q: float = 0.7071) -> list[float]:
    w = 2 * math.pi * freq / RATE
    c, alpha = math.cos(w), math.sin(w) / (2 * q)
    return biquad(x, (1 + c) / 2, -(1 + c), (1 + c) / 2, 1 + alpha, -2 * c, 1 - alpha)


def peaking(x: list[float], freq: float, gain_db: float, q: float = 0.9) -> list[float]:
    a = 10 ** (gain_db / 40)
    w = 2 * math.pi * freq / RATE
    c, alpha = math.cos(w), math.sin(w) / (2 * q)
    return biquad(x, 1 + alpha * a, -2 * c, 1 - alpha * a, 1 + alpha / a, -2 * c, 1 - alpha / a)


def compress(x: list[float], threshold_db: float = -24.0, ratio: float = 3.0,
             attack_ms: float = 5.0, release_ms: float = 90.0) -> list[float]:
    """输入为 -1..1；超过阈值的部分按比例压缩，让轻声音节也听得见。"""
    attack = math.exp(-1 / (RATE * attack_ms / 1000))
    release = math.exp(-1 / (RATE * release_ms / 1000))
    threshold = 10 ** (threshold_db / 20)
    envelope, out = 0.0, []
    for s in x:
        level = abs(s)
        coeff = attack if level > envelope else release
        envelope = coeff * envelope + (1 - coeff) * level
        if envelope > threshold:
            s *= threshold * (envelope / threshold) ** (1 / ratio) / envelope
        out.append(s)
    return out


def normalize(x: list[float], peak_db: float) -> list[float]:
    gain = dbfs(peak_db) / (max((abs(v) for v in x), default=0.0) or 1.0)
    return [v * gain for v in x]


def speaker_voice(text: str, workdir: Path, name: str) -> list[float]:
    """去掉小喇叭放不出的低频、突出辅音、压缩动态，并留出功放余量。"""
    x = synthesize(text, workdir, name)
    x = highpass(highpass(x, 300), 300)
    x = peaking(x, 3000, 5)
    peak = max((abs(v) for v in x), default=0.0) or 1.0
    return normalize(compress([v / peak for v in x]), -6)


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
        intro = speaker_voice(INTRO, Path(tmp), "intro")
        outro = speaker_voice(OUTRO, Path(tmp), "outro")

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
