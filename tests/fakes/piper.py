"""Tiny fake Piper CLI for exercising real subprocess I/O without Piper or a model."""

import argparse
import sys
import time
import wave
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output_file", type=Path, required=True)
    args = parser.parse_args()
    text = sys.stdin.buffer.read()
    if text == b"timeout\n":
        time.sleep(10)
    if text == b"fail\n":
        sys.exit(3)
    if text == b"corrupt\n":
        args.output_file.write_bytes(b"invalid WAV")
        return
    with wave.open(str(args.output_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22_050)
        wav.writeframes(len(text).to_bytes(2, "little") * 64)


if __name__ == "__main__":
    main()
