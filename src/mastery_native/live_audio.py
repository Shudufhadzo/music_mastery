from __future__ import annotations

import math
import subprocess
import threading
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QIODevice, QObject
from scipy.signal import butter, sosfilt

from mastery_native.engine import MasteringControls, hidden_subprocess_kwargs
from mastery_native.toolchain import resolve_ffmpeg_path


DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 2


@dataclass(slots=True)
class LiveAudioTrack:
    path: str
    sample_rate: int
    original_audio: np.ndarray
    mastered_audio: np.ndarray
    original_waveform: list[float]
    mastered_waveform: list[float]
    source_level_db: float
    estimated_bpm: float | None = None


def decode_audio_file(path: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    ffmpeg_path = resolve_ffmpeg_path()
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        path,
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(DEFAULT_CHANNELS),
        "-ar",
        str(sample_rate),
        "-",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        **hidden_subprocess_kwargs(),
    )
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if audio.size == 0:
        return np.zeros((0, DEFAULT_CHANNELS), dtype=np.float32)
    return audio.reshape(-1, DEFAULT_CHANNELS).copy()


def measure_audio_level_db(audio: np.ndarray) -> float:
    if audio.size == 0:
        return -24.0
    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    if rms <= 1e-8:
        return -24.0
    return 20.0 * math.log10(rms)


def build_waveform_peaks(audio: np.ndarray, points: int = 240) -> list[float]:
    if points <= 0:
        return []
    if audio.size == 0:
        return [0.0] * points

    mono = np.max(np.abs(audio), axis=1)
    frames_per_bucket = max(1, int(math.ceil(len(mono) / points)))
    peaks: list[float] = []
    for index in range(points):
        start = index * frames_per_bucket
        end = min(len(mono), start + frames_per_bucket)
        if start >= len(mono):
            peaks.append(0.0)
            continue
        peaks.append(float(np.max(mono[start:end])))
    return peaks


def pcm16le_bytes(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    int16_audio = np.round(clipped * 32767.0).astype(np.int16)
    return int16_audio.tobytes()


def load_live_audio_track(path: str, *, waveform_points: int = 240) -> LiveAudioTrack:
    original_audio = decode_audio_file(path)
    source_level_db = measure_audio_level_db(original_audio)
    waveform = build_waveform_peaks(original_audio, points=waveform_points)
    estimated_bpm = estimate_bpm(original_audio, DEFAULT_SAMPLE_RATE)
    return LiveAudioTrack(
        path=path,
        sample_rate=DEFAULT_SAMPLE_RATE,
        original_audio=original_audio,
        mastered_audio=original_audio.copy(),
        original_waveform=waveform,
        mastered_waveform=list(waveform),
        source_level_db=source_level_db,
        estimated_bpm=estimated_bpm,
    )


def estimate_bpm(audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> float | None:
    if audio.size == 0 or len(audio) < sample_rate * 4:
        return None

    mono = np.mean(np.abs(audio), axis=1)
    hop = 1024
    usable = len(mono) - (len(mono) % hop)
    if usable <= hop * 8:
        return None

    envelope = mono[:usable].reshape(-1, hop).mean(axis=1)
    onset = np.maximum(0.0, np.diff(envelope, prepend=envelope[0]))
    onset -= float(np.mean(onset))
    if not np.any(onset > 0):
        return None

    frame_rate = sample_rate / hop
    min_bpm = 70.0
    max_bpm = 180.0
    min_lag = int(frame_rate * 60.0 / max_bpm)
    max_lag = int(frame_rate * 60.0 / min_bpm)
    if max_lag <= min_lag:
        return None

    autocorr = np.correlate(onset, onset, mode="full")[len(onset) - 1 :]
    search = autocorr[min_lag:max_lag + 1]
    if search.size == 0:
        return None

    lag = min_lag + int(np.argmax(search))
    if lag <= 0:
        return None
    return round(60.0 * frame_rate / lag, 1)


def apply_live_mastering(
    audio: np.ndarray,
    controls: MasteringControls,
    *,
    source_level_db: float,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> np.ndarray:
    if audio.size == 0:
        return np.zeros_like(audio)

    processed = np.array(audio, dtype=np.float32, copy=True)
    cleanup_cutoff = max(20, min(80, int(controls.low_cut_hz)))
    if cleanup_cutoff > 20:
        processed = _apply_sos(processed, butter(2, cleanup_cutoff, btype="highpass", fs=sample_rate, output="sos"))

    bass_gain = _centered_gain(controls.bass_percent, 6.0)
    if abs(bass_gain) >= 0.1:
        processed = _apply_biquad(processed, _low_shelf_sos(sample_rate, 100.0, bass_gain))

    voice_gain = _centered_gain(controls.clarity_percent, 4.0)
    if abs(voice_gain) >= 0.1:
        processed = _apply_biquad(processed, _peaking_sos(sample_rate, 2500.0, 1.2, voice_gain))

    mud_cut = -max(0.0, (controls.clarity_percent - 50) / 50 * 2.0)
    if abs(mud_cut) >= 0.1:
        processed = _apply_biquad(processed, _peaking_sos(sample_rate, 320.0, 1.0, mud_cut))

    treble_gain = _centered_gain(controls.treble_percent, 5.0)
    if abs(treble_gain) >= 0.1:
        processed = _apply_biquad(processed, _high_shelf_sos(sample_rate, 4500.0, treble_gain))

    high_cut = max(6000, min(20000, int(controls.high_cut_hz)))
    if high_cut < 20000:
        processed = _apply_sos(processed, butter(2, high_cut, btype="lowpass", fs=sample_rate, output="sos"))

    if controls.auto_eq:
        processed = _apply_biquad(processed, _peaking_sos(sample_rate, 180.0, 1.0, -1.0))
        processed = _apply_biquad(processed, _peaking_sos(sample_rate, 4200.0, 1.0, 1.2))

    processed = _apply_punch(processed, controls.punch_percent)
    processed = _apply_stereo_width(processed, controls.stereo_width_percent)
    processed = _match_target_level(processed, controls.target_lufs, source_level_db)
    if abs(controls.gain_db) >= 0.05:
        processed = processed * (10.0 ** (controls.gain_db / 20.0))

    if controls.true_peak_limiter:
        peak = float(np.max(np.abs(processed)))
        if peak > 0.98:
            processed = processed * (0.98 / peak)
    else:
        processed = np.clip(processed, -1.0, 1.0)

    return processed.astype(np.float32, copy=False)


class SwitchableAudioDevice(QIODevice):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._source_bytes: dict[str, bytes] = {"original": b"", "mastered": b""}
        self._active_source = "original"
        self._position = 0

    def set_source_bytes(self, source: str, payload: bytes) -> None:
        with self._lock:
            self._source_bytes[source] = payload
            current_length = len(self._source_bytes.get(self._active_source, b""))
            self._position = min(self._position, current_length)

    def set_active_source(self, source: str) -> None:
        with self._lock:
            self._active_source = source
            current_length = len(self._source_bytes.get(self._active_source, b""))
            self._position = min(self._position, current_length)

    def current_position(self) -> int:
        with self._lock:
            return self._position

    def source_length(self, source: str) -> int:
        with self._lock:
            return len(self._source_bytes.get(source, b""))

    def seek_to(self, offset: int) -> None:
        with self._lock:
            current_length = len(self._source_bytes.get(self._active_source, b""))
            self._position = max(0, min(offset, current_length))

    def start(self) -> None:
        self.open(QIODevice.OpenModeFlag.ReadOnly)

    def stop(self) -> None:
        with self._lock:
            self._position = 0
        self.close()

    def bytesAvailable(self) -> int:  # type: ignore[override]
        with self._lock:
            current_length = len(self._source_bytes.get(self._active_source, b""))
            remaining = max(0, current_length - self._position)
        return remaining + super().bytesAvailable()

    def readData(self, maxlen: int) -> bytes:  # type: ignore[override]
        with self._lock:
            payload = self._source_bytes.get(self._active_source, b"")
            if self._position >= len(payload):
                return b""
            chunk = payload[self._position:self._position + maxlen]
            self._position += len(chunk)
            return chunk

    def writeData(self, _data: bytes) -> int:  # type: ignore[override]
        return 0


def _centered_gain(percent: int, max_gain_db: float) -> float:
    clamped = max(0, min(100, percent))
    return ((clamped - 50) / 50) * max_gain_db


def _apply_sos(audio: np.ndarray, sos: np.ndarray) -> np.ndarray:
    return np.column_stack([sosfilt(sos, audio[:, 0]), sosfilt(sos, audio[:, 1])]).astype(np.float32)


def _apply_biquad(audio: np.ndarray, coeffs: tuple[float, float, float, float, float, float]) -> np.ndarray:
    b0, b1, b2, a0, a1, a2 = coeffs
    sos = np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]], dtype=np.float64)
    return _apply_sos(audio, sos)


def _match_target_level(audio: np.ndarray, target_db: float, source_level_db: float) -> np.ndarray:
    measured_db = measure_audio_level_db(audio)
    if abs(target_db - source_level_db) < 0.05 and abs(measured_db - source_level_db) < 0.05:
        return audio

    gain_db = target_db - measured_db
    gain = math.pow(10.0, gain_db / 20.0)
    return (audio * gain).astype(np.float32)


def _apply_punch(audio: np.ndarray, percent: int) -> np.ndarray:
    amount = max(0.0, min(100.0, percent)) / 100.0
    if abs(amount - 0.5) < 0.01:
        return audio

    drive = 1.0 + max(0.0, amount - 0.5) * 1.8
    softened = np.tanh(audio * drive) / drive
    if amount >= 0.5:
        mix = (amount - 0.5) * 2.0
        return ((1.0 - mix) * audio + mix * softened).astype(np.float32)

    smooth_mix = (0.5 - amount) * 2.0
    return ((1.0 - smooth_mix) * audio + smooth_mix * (audio * 0.92)).astype(np.float32)


def _apply_stereo_width(audio: np.ndarray, percent: int) -> np.ndarray:
    width = 1.0 + ((max(0, min(100, percent)) - 50) / 50) * 0.6
    left = audio[:, 0]
    right = audio[:, 1]
    mid = (left + right) * 0.5
    side = (left - right) * 0.5 * width
    widened = np.column_stack([mid + side, mid - side])
    return widened.astype(np.float32)


def _peaking_sos(sample_rate: int, frequency: float, q: float, gain_db: float) -> tuple[float, float, float, float, float, float]:
    a = math.pow(10.0, gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    return (b0, b1, b2, a0, a1, a2)


def _low_shelf_sos(sample_rate: int, frequency: float, gain_db: float, slope: float = 1.0) -> tuple[float, float, float, float, float, float]:
    a = math.pow(10.0, gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) - (a - 1) * cos_w0 + beta)
    b1 = 2 * a * ((a - 1) - (a + 1) * cos_w0)
    b2 = a * ((a + 1) - (a - 1) * cos_w0 - beta)
    a0 = (a + 1) + (a - 1) * cos_w0 + beta
    a1 = -2 * ((a - 1) + (a + 1) * cos_w0)
    a2 = (a + 1) + (a - 1) * cos_w0 - beta
    return (b0, b1, b2, a0, a1, a2)


def _high_shelf_sos(sample_rate: int, frequency: float, gain_db: float, slope: float = 1.0) -> tuple[float, float, float, float, float, float]:
    a = math.pow(10.0, gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1) + (a - 1) * cos_w0 + beta)
    b1 = -2 * a * ((a - 1) + (a + 1) * cos_w0)
    b2 = a * ((a + 1) + (a - 1) * cos_w0 - beta)
    a0 = (a + 1) - (a - 1) * cos_w0 + beta
    a1 = 2 * ((a - 1) - (a + 1) * cos_w0)
    a2 = (a + 1) - (a - 1) * cos_w0 - beta
    return (b0, b1, b2, a0, a1, a2)
