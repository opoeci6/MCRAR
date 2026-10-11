"""Decode audio with `soundfile` only (WAV, FLAC, OGG/Vorbis/Opus, MP3 via bundled libsndfile).

librosa's `audioread` fallback is deliberately not used: it would shell out to whatever ffmpeg
happens to be on PATH. Formats libsndfile cannot read (m4a/aac/...) and corrupt files raise
`UnsupportedAudioError` / `AudioDecodeError`. Error messages name the format or extension but
never include file contents.
"""

from __future__ import annotations

import contextlib
import io
import os
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np
import soundfile as sf
import soxr

AudioSource = str | os.PathLike[str] | bytes | bytearray | memoryview | BinaryIO

# Extensions libsndfile cannot decode (used only to word the error).
_UNSUPPORTED_EXTS = {".m4a", ".aac", ".mp4", ".m4b", ".wma", ".ac3", ".amr", ".mka", ".webm"}
# Extensions libsndfile can decode; a failure on one of these is a decode (corruption) error.
_SUPPORTED_EXTS = {
    ".wav", ".wave", ".flac", ".ogg", ".oga", ".opus", ".mp3", ".aif", ".aiff", ".au", ".caf",
    ".w64", ".rf64",
}  # fmt: skip
_SUPPORTED_MAGIC = (b"RIFF", b"RF64", b"fLaC", b"OggS", b"ID3", b"FORM", b".snd", b"caff")


class AudioError(Exception):
    """Base class for audio loading errors."""


class UnsupportedAudioError(AudioError):
    """The container/codec is not something soundfile can decode (e.g. m4a/aac)."""


class AudioDecodeError(AudioError):
    """The file looks like a supported format but is corrupt, truncated or unreadable."""


@dataclass(frozen=True)
class AudioInfo:
    """Header-level facts about an audio file (nothing is decoded)."""

    duration_s: float
    sr: int
    channels: int
    format: str
    subtype: str


@dataclass(frozen=True, eq=False)
class AudioClip:
    """Decoded audio. `samples` is float32 in [-1, 1]: shape (n,) if mono else (n, channels).

    `sr` is the rate of `samples`; `original_sr` is the file's native rate. `channels` is the
    original channel count and `duration_s` the duration of the whole file, even when
    `max_seconds` truncated the decoded samples.
    """

    samples: np.ndarray
    sr: int
    channels: int
    duration_s: float
    format: str
    subtype: str
    original_sr: int


def _hint(source: AudioSource) -> str:
    if isinstance(source, str | os.PathLike):
        return Path(source).suffix.lower()
    name = getattr(source, "name", None)
    if isinstance(name, str):
        return Path(name).suffix.lower()
    return ""


@contextlib.contextmanager
def _open_binary(source: AudioSource) -> Iterator[BinaryIO]:
    if isinstance(source, str | os.PathLike):
        try:
            handle = open(source, "rb")  # noqa: SIM115 - closed by the with-block below
        except FileNotFoundError:
            raise AudioDecodeError("audio file not found") from None
        except OSError as exc:
            raise AudioDecodeError(f"cannot open audio file ({type(exc).__name__})") from None
        with handle:
            yield handle
    elif isinstance(source, bytes | bytearray | memoryview):
        yield io.BytesIO(bytes(source))
    elif hasattr(source, "read"):
        yield source
    else:
        raise TypeError(f"unsupported audio source type: {type(source).__name__}")


def _check_wav_complete(fh: BinaryIO) -> None:
    """Raise AudioDecodeError if a RIFF/WAVE data chunk claims more bytes than the file has.

    libsndfile silently shortens truncated WAVs, so this has to be checked explicitly.
    """
    try:
        start = fh.tell()
    except (OSError, ValueError):
        return  # not seekable: leave it to libsndfile
    try:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        fh.seek(start)
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return
        pos = start + 12
        while pos + 8 <= end:
            fh.seek(pos)
            cid, size = struct.unpack("<4sI", fh.read(8))
            if cid == b"data":
                if size != 0xFFFFFFFF and pos + 8 + size > end:
                    raise AudioDecodeError("truncated WAV file: data chunk is incomplete")
                return
            pos += 8 + size + (size & 1)
    except (OSError, struct.error, ValueError):
        return
    finally:
        with contextlib.suppress(OSError, ValueError):
            fh.seek(start)


def _classify_open_failure(fh: BinaryIO, hint: str) -> AudioError:
    try:
        pos = fh.tell()
        magic = fh.read(12)
        fh.seek(pos)
    except (OSError, ValueError):
        magic = b""
    if hint in _UNSUPPORTED_EXTS or magic[4:8] == b"ftyp":
        return UnsupportedAudioError(
            f"unsupported audio format '{hint or 'mp4/m4a'}': "
            "only WAV, FLAC, OGG/Vorbis/Opus and MP3 are supported"
        )
    if hint in _SUPPORTED_EXTS or magic.startswith(_SUPPORTED_MAGIC):
        label = hint or "audio"
        return AudioDecodeError(f"could not decode {label} file: it is corrupt or truncated")
    shown = f" '{hint}'" if hint else ""
    return UnsupportedAudioError(
        f"unrecognised audio format{shown}: only WAV, FLAC, OGG/Vorbis/Opus and MP3 are supported"
    )


def _open(fh: BinaryIO, hint: str) -> sf.SoundFile:
    _check_wav_complete(fh)
    try:
        return sf.SoundFile(fh)
    except (sf.LibsndfileError, RuntimeError):
        raise _classify_open_failure(fh, hint) from None


def _info_of(f: sf.SoundFile) -> AudioInfo:
    return AudioInfo(
        duration_s=float(f.frames) / f.samplerate if f.samplerate else 0.0,
        sr=int(f.samplerate),
        channels=int(f.channels),
        format=str(f.format),
        subtype=str(f.subtype),
    )


def probe_audio(source: AudioSource) -> AudioInfo:
    """Duration, sample rate, channels and format without decoding any samples."""
    with _open_binary(source) as fh, _open(fh, _hint(source)) as f:
        return _info_of(f)


def load_audio(
    source: AudioSource,
    *,
    sr: int | None = None,
    mono: bool = True,
    max_seconds: float | None = None,
) -> AudioClip:
    """Decode `source` (path, bytes or binary file-like) to float32 samples in [-1, 1].

    sr: target sample rate (soxr "VHQ" resampling); None keeps the native rate.
    mono: average channels to mono; otherwise samples have shape (n, channels).
    max_seconds: decode only the first N seconds (the rest of the file is not decoded);
        `duration_s` still reports the whole file.
    """
    if sr is not None and sr <= 0:
        raise ValueError("sr must be positive")
    if max_seconds is not None and max_seconds <= 0:
        raise ValueError("max_seconds must be positive")
    with _open_binary(source) as fh, _open(fh, _hint(source)) as f:
        info = _info_of(f)
        frames = -1 if max_seconds is None else int(max_seconds * f.samplerate)
        try:
            data = f.read(frames, dtype="float32", always_2d=True)
        except (sf.LibsndfileError, RuntimeError):
            raise AudioDecodeError(
                f"could not decode {info.format} audio: it is corrupt or truncated"
            ) from None
    if data.shape[1] == 1:
        data = data[:, 0]
    elif mono:
        data = data.mean(axis=1, dtype=np.float32)
    out_sr = info.sr
    if sr is not None and sr != info.sr:
        out_sr = sr
        if data.shape[0] > 0:
            data = soxr.resample(np.ascontiguousarray(data), info.sr, sr, quality="VHQ")
    samples = np.clip(np.ascontiguousarray(data, dtype=np.float32), -1.0, 1.0)
    return AudioClip(
        samples=samples,
        sr=out_sr,
        channels=info.channels,
        duration_s=info.duration_s,
        format=info.format,
        subtype=info.subtype,
        original_sr=info.sr,
    )
