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
        validate_wav_bytes(audio, sample_rate=sample_rate, channels=channels)
        return audio
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        raise TtsOutputValidationError from exc


def validate_wav_bytes(audio: bytes, *, sample_rate: int | None, channels: int) -> None:
    """Check in-memory replay audio without writing another temporary file."""
    if not 0 < len(audio) <= MAX_AUDIO_BYTES:
        raise TtsOutputValidationError
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            if (
                wav.getcomptype() != "NONE"
                or wav.getnchannels() != channels
                or wav.getsampwidth() != 2
                or not 8_000 <= wav.getframerate() <= 192_000
                or (sample_rate is not None and wav.getframerate() != sample_rate)
                or wav.getnframes() <= 0
            ):
                raise TtsOutputValidationError
            expected_size = wav.getnframes() * channels * 2
            if (
                expected_size > MAX_AUDIO_BYTES
                or len(wav.readframes(wav.getnframes())) != expected_size
            ):
                raise TtsOutputValidationError
    except (EOFError, ValueError, wave.Error) as exc:
        raise TtsOutputValidationError from exc
