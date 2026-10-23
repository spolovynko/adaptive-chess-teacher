"""Validate bounded PCM WAV output before making it available to callers."""

import io
import stat
import wave
from pathlib import Path

from voicechess.tts.errors import TtsOutputValidationError

# Announcement output is short; reject oversized files before loading into memory.
MAX_AUDIO_BYTES = 16 * 1024 * 1024


def read_validated_wav(path: Path, *, sample_rate: int, channels: int) -> bytes:
    """Read complete, nonempty 16-bit PCM WAV bytes at the expected native rate."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_AUDIO_BYTES:
            raise TtsOutputValidationError
        with path.open("rb") as audio_file:
            audio = audio_file.read(MAX_AUDIO_BYTES + 1)
        if len(audio) > MAX_AUDIO_BYTES:
            raise TtsOutputValidationError
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (
                wav.getcomptype() != "NONE"
                or wav.getnchannels() != channels
                or wav.getsampwidth() != 2
                or wav.getframerate() != sample_rate
                or wav.getnframes() <= 0
            ):
                raise TtsOutputValidationError
            expected_size = wav.getnframes() * channels * 2
            if (
                expected_size > MAX_AUDIO_BYTES
                or len(wav.readframes(wav.getnframes())) != expected_size
            ):
                raise TtsOutputValidationError
        return audio
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise TtsOutputValidationError from exc
