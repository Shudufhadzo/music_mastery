import numpy as np

from mastery_native.engine import MasteringControls
from mastery_native.live_audio import (
    SwitchableAudioDevice,
    apply_live_mastering,
    build_waveform_peaks,
    measure_audio_level_db,
)


def _stereo_test_tone(sample_rate: int = 44100, duration_seconds: float = 0.25) -> np.ndarray:
    timeline = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    left = 0.35 * np.sin(2 * np.pi * 120 * timeline) + 0.15 * np.sin(2 * np.pi * 2600 * timeline)
    right = 0.30 * np.sin(2 * np.pi * 160 * timeline) + 0.12 * np.sin(2 * np.pi * 4800 * timeline)
    return np.column_stack([left, right]).astype(np.float32)


def test_apply_live_mastering_stays_neutral_when_controls_match_source_level():
    audio = _stereo_test_tone()
    source_level = measure_audio_level_db(audio)
    controls = MasteringControls(
        target_lufs=source_level,
        low_cut_hz=20,
        clarity_percent=50,
        bass_percent=50,
        treble_percent=50,
        punch_percent=50,
        stereo_width_percent=50,
        auto_eq=False,
    )

    processed = apply_live_mastering(audio, controls, source_level_db=source_level)

    assert processed.shape == audio.shape
    assert np.max(np.abs(processed - audio)) < 0.02


def test_apply_live_mastering_changes_tone_and_keeps_safe_peak():
    audio = _stereo_test_tone()
    source_level = measure_audio_level_db(audio)
    controls = MasteringControls(
        target_lufs=source_level + 1.5,
        clarity_percent=80,
        bass_percent=72,
        treble_percent=65,
        punch_percent=78,
        stereo_width_percent=65,
        low_cut_hz=28,
        auto_eq=True,
    )

    processed = apply_live_mastering(audio, controls, source_level_db=source_level)

    assert processed.shape == audio.shape
    assert not np.allclose(processed, audio)
    assert np.max(np.abs(processed)) <= 0.99


def test_apply_live_mastering_uses_gain_and_high_cut_controls():
    audio = _stereo_test_tone()
    source_level = measure_audio_level_db(audio)
    controls = MasteringControls(
        target_lufs=source_level,
        gain_db=6.0,
        high_cut_hz=6000,
        clarity_percent=50,
        bass_percent=50,
        treble_percent=50,
        punch_percent=50,
        stereo_width_percent=50,
        low_cut_hz=20,
        auto_eq=False,
    )

    processed = apply_live_mastering(audio, controls, source_level_db=source_level)

    assert processed.shape == audio.shape
    assert not np.allclose(processed, audio)
    assert np.max(np.abs(processed)) <= 0.99


def test_build_waveform_peaks_returns_requested_number_of_points():
    audio = _stereo_test_tone()

    peaks = build_waveform_peaks(audio, points=64)

    assert len(peaks) == 64
    assert all(0.0 <= peak <= 1.0 for peak in peaks)


def test_switchable_audio_device_keeps_position_when_switching_sources():
    device = SwitchableAudioDevice(parent=None)
    device.set_source_bytes("original", b"01234567")
    device.set_source_bytes("mastered", b"ABCDEFGH")
    device.set_active_source("original")
    device.start()

    assert device.readData(4) == b"0123"

    device.set_active_source("mastered")

    assert device.readData(2) == b"EF"


def test_switchable_audio_device_stop_resets_to_start():
    device = SwitchableAudioDevice(parent=None)
    device.set_source_bytes("original", b"abcdefgh")
    device.set_active_source("original")
    device.start()
    device.readData(3)

    device.stop()
    device.start()

    assert device.readData(3) == b"abc"
