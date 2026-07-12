#!/usr/bin/env python3
"""Generate deterministic PCM WAV input for tests without recording a person."""

from __future__ import annotations

import argparse
import math
import struct
import wave
from pathlib import Path


def generate_wav(
    output: Path,
    duration: float,
    sample_rate: int,
    frequency: float,
    amplitude: float,
) -> None:
    """Write mono signed 16-bit PCM; frequency=0 produces silence."""
    frame_count = round(duration * sample_rate)
    peak = int(32767 * amplitude)
    output.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(output), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(frame_count):
            sample = 0
            if frequency > 0:
                sample = round(
                    peak * math.sin(2 * math.pi * frequency * index / sample_rate)
                )
            wav_file.writeframesraw(struct.pack("<h", sample))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("mock-audio.wav"))
    parser.add_argument("--duration", type=float, default=1.0, help="seconds")
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument(
        "--frequency",
        type=float,
        default=440.0,
        help="tone frequency in Hz; use 0 for silence",
    )
    parser.add_argument("--amplitude", type=float, default=0.1, help="0.0 to 1.0")
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if args.sample_rate <= 0:
        parser.error("--sample-rate must be greater than zero")
    if args.frequency < 0:
        parser.error("--frequency cannot be negative")
    if not 0 <= args.amplitude <= 1:
        parser.error("--amplitude must be between 0 and 1")
    return args


def main() -> None:
    args = parse_args()
    generate_wav(
        output=args.output,
        duration=args.duration,
        sample_rate=args.sample_rate,
        frequency=args.frequency,
        amplitude=args.amplitude,
    )
    print(
        f"wrote {args.output} ({args.duration:.3f}s, {args.sample_rate} Hz, mono PCM16)"
    )


if __name__ == "__main__":
    main()
