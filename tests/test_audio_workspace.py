"""Selective cleanup and exclusive ownership of private audio work files."""

import logging
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from voicechess.tts import TtsStorageError
from voicechess.tts.workspace import AudioWorkspace


def workspace(tmp_path: Path) -> AudioWorkspace:
    return AudioWorkspace(audio_dir=tmp_path / "audio", logger=logging.getLogger("tts-test"))


def test_private_work_files_are_removed_after_success_and_failure(tmp_path: Path) -> None:
    owner = workspace(tmp_path)
    owner.start()
    try:
        with owner.work_directory() as path:
            (path / "speech.wav").write_bytes(b"fake output")
        assert not path.exists()
        with pytest.raises(ValueError):
            with owner.work_directory() as failed:
                (failed / "speech.partial.wav").write_bytes(b"partial output")
                raise ValueError("synthesis failed")
        assert not failed.exists()
    finally:
        owner.stop()


def test_only_one_owner_may_start_and_clean_a_directory(tmp_path: Path) -> None:
    first, second = workspace(tmp_path), workspace(tmp_path)
    first.start()
    try:
        with first.work_directory() as active:
            output = active / "speech.partial.wav"
            output.write_bytes(b"active output")
            with pytest.raises(TtsStorageError):
                second.start()
            assert output.read_bytes() == b"active output"
    finally:
        first.stop()
    second.start()
    second.stop()


def test_startup_cleans_owned_leftovers_and_preserves_unrelated_files(tmp_path: Path) -> None:
    root = tmp_path / "audio"
    abandoned = root / "voicechess" / f"piper-{uuid4().hex}"
    abandoned.mkdir(parents=True)
    (abandoned / "speech.partial.wav").write_bytes(b"abandoned")
    unrelated = root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    reserved_unknown = abandoned.parent / "user-notes.txt"
    reserved_unknown.write_text("keep too", encoding="utf-8")
    owner = workspace(tmp_path)
    owner.start()
    try:
        assert not abandoned.exists()
        assert unrelated.read_text(encoding="utf-8") == "keep"
        assert reserved_unknown.read_text(encoding="utf-8") == "keep too"
    finally:
        owner.stop()


def test_unknown_nested_files_are_not_recursively_deleted(tmp_path: Path) -> None:
    abandoned = tmp_path / "audio" / "voicechess" / f"piper-{uuid4().hex}"
    abandoned.mkdir(parents=True)
    unknown = abandoned / "keep.txt"
    unknown.write_text("keep", encoding="utf-8")
    owner = workspace(tmp_path)
    with pytest.raises(TtsStorageError):
        owner.start()
    assert unknown.read_text(encoding="utf-8") == "keep"


def test_stopped_workspace_cannot_create_work_until_restarted(tmp_path: Path) -> None:
    owner = workspace(tmp_path)
    with pytest.raises(TtsStorageError):
        with owner.work_directory():
            pytest.fail("unstarted workspace accepted work")
    owner.start()
    owner.start()
    owner.stop()
    owner.stop()
    with pytest.raises(TtsStorageError):
        with owner.work_directory():
            pytest.fail("stopped workspace accepted work")
    owner.start()
    owner.stop()


def test_active_work_prevents_release_or_a_second_work_directory(tmp_path: Path) -> None:
    owner = workspace(tmp_path)
    owner.start()
    try:
        with owner.work_directory():
            with pytest.raises(TtsStorageError):
                owner.stop()
            with pytest.raises(TtsStorageError):
                with owner.work_directory():
                    pytest.fail("two active work directories")
    finally:
        owner.stop()


def test_cleanup_error_blocks_new_work_and_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = workspace(tmp_path)
    owner.start()

    def blocked_unlink(path: Path, missing_ok: bool = False) -> None:
        raise PermissionError("private path")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", blocked_unlink)
            with pytest.raises(TtsStorageError):
                with owner.work_directory() as path:
                    (path / "speech.partial.wav").write_bytes(b"partial")
            assert path.exists()
            with pytest.raises(TtsStorageError):
                with owner.work_directory():
                    pytest.fail("more work accepted before cleanup")
        owner.start()
        assert not path.exists()
    finally:
        owner.stop()


def test_crashed_owner_releases_lock_and_restart_removes_abandoned_audio(tmp_path: Path) -> None:
    root = tmp_path / "audio"
    script = (
        "import logging, os, sys\n"
        "from pathlib import Path\n"
        "from voicechess.tts.workspace import AudioWorkspace\n"
        "owner = AudioWorkspace(audio_dir=Path(sys.argv[1]), logger=logging.getLogger('fake'))\n"
        "owner.start()\n"
        "work = owner.work_directory()\n"
        "path = work.__enter__()\n"
        "(path / 'speech.partial.wav').write_bytes(b'abandoned')\n"
        "os._exit(0)\n"
    )
    subprocess.run([sys.executable, "-c", script, str(root)], check=True, timeout=5)
    assert len(list((root / "voicechess").glob("piper-*"))) == 1
    owner = workspace(tmp_path)
    owner.start()
    try:
        assert list((root / "voicechess").glob("piper-*")) == []
    finally:
        owner.stop()


def test_failed_startup_releases_lease_for_a_retry(tmp_path: Path) -> None:
    reserved = tmp_path / "audio" / "voicechess"
    reserved.mkdir(parents=True)
    bad = reserved / f"piper-{uuid4().hex}"
    bad.write_bytes(b"not a directory")
    first = workspace(tmp_path)
    with pytest.raises(TtsStorageError):
        first.start()
    bad.unlink()
    second = workspace(tmp_path)
    second.start()
    second.stop()


def test_unsafe_workspace_link_is_rejected_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a Windows junction deterministically without requiring admin privileges.
    reserved = tmp_path / "audio" / "voicechess"
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == reserved or original(path))
    with pytest.raises(TtsStorageError):
        workspace(tmp_path).start()
    assert not reserved.exists()


def test_changed_parent_directory_cannot_redirect_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = workspace(tmp_path)
    reserved = tmp_path / "audio" / "voicechess"
    original = Path.resolve

    def redirected(path: Path, strict: bool = False) -> Path:
        return tmp_path / "outside" if path == reserved else original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(TtsStorageError):
        owner.start()
    assert not reserved.exists()
