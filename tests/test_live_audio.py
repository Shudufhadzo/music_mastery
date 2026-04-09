import numpy as np
import pytest

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


def test_apply_live_mastering_keeps_getting_louder_above_three_db_with_peak_safety():
    timeline = np.linspace(0, 0.4, int(44100 * 0.4), endpoint=False)
    audio = np.column_stack(
        [
            0.7 * np.sin(2 * np.pi * 220 * timeline),
            0.7 * np.sin(2 * np.pi * 330 * timeline),
        ]
    ).astype(np.float32)
    source_level = measure_audio_level_db(audio)

    moderate_boost = apply_live_mastering(
        audio,
        MasteringControls(
            target_lufs=source_level,
            gain_db=3.0,
            clarity_percent=50,
            bass_percent=50,
            treble_percent=50,
            punch_percent=50,
            stereo_width_percent=50,
            low_cut_hz=20,
            auto_eq=False,
            true_peak_limiter=True,
        ),
        source_level_db=source_level,
    )
    heavy_boost = apply_live_mastering(
        audio,
        MasteringControls(
            target_lufs=source_level,
            gain_db=9.0,
            clarity_percent=50,
            bass_percent=50,
            treble_percent=50,
            punch_percent=50,
            stereo_width_percent=50,
            low_cut_hz=20,
            auto_eq=False,
            true_peak_limiter=True,
        ),
        source_level_db=source_level,
    )

    assert measure_audio_level_db(heavy_boost) > measure_audio_level_db(moderate_boost) + 0.75
    assert np.max(np.abs(heavy_boost)) <= 0.99


@pytest.mark.parametrize(
    ("attribute", "value", "minimum_change"),
    [
        ("clarity_percent", 100, 0.08),
        ("bass_percent", 100, 0.20),
        ("treble_percent", 100, 0.06),
        ("punch_percent", 100, 0.12),
        ("stereo_width_percent", 100, 0.12),
        ("low_cut_hz", 80, 0.20),
        ("high_cut_hz", 12000, 0.06),
    ],
)
def test_apply_live_mastering_main_dials_change_audio_at_strong_settings(attribute, value, minimum_change):
    timeline = np.linspace(0, 0.5, int(44100 * 0.5), endpoint=False)
    audio = np.column_stack(
        [
            0.58 * np.sin(2 * np.pi * 80 * timeline)
            + 0.22 * np.sin(2 * np.pi * 220 * timeline)
            + 0.12 * np.sin(2 * np.pi * 2500 * timeline)
            + 0.08 * np.sin(2 * np.pi * 7000 * timeline),
            0.54 * np.sin(2 * np.pi * 95 * timeline)
            + 0.20 * np.sin(2 * np.pi * 330 * timeline)
            + 0.10 * np.sin(2 * np.pi * 3200 * timeline)
            + 0.07 * np.sin(2 * np.pi * 8500 * timeline),
        ]
    ).astype(np.float32)
    source_level = measure_audio_level_db(audio)

    neutral = MasteringControls(target_lufs=source_level, true_peak_limiter=True, auto_eq=False)
    boosted = MasteringControls(target_lufs=source_level, true_peak_limiter=True, auto_eq=False)
    setattr(boosted, attribute, value)

    neutral_output = apply_live_mastering(audio, neutral, source_level_db=source_level)
    boosted_output = apply_live_mastering(audio, boosted, source_level_db=source_level)

    assert np.max(np.abs(boosted_output - neutral_output)) >= minimum_change
    assert np.max(np.abs(boosted_output)) <= 0.99


def test_apply_live_mastering_target_loudness_boost_increases_output_level():
    audio = _stereo_test_tone()
    source_level = measure_audio_level_db(audio)

    neutral = apply_live_mastering(
        audio,
        MasteringControls(target_lufs=source_level, true_peak_limiter=True, auto_eq=False),
        source_level_db=source_level,
    )
    louder = apply_live_mastering(
        audio,
        MasteringControls(target_lufs=-8.0, true_peak_limiter=True, auto_eq=False),
        source_level_db=source_level,
    )

    assert measure_audio_level_db(louder) > measure_audio_level_db(neutral) + 1.0
    assert np.max(np.abs(louder)) <= 0.99


def test_apply_live_mastering_auto_eq_toggle_changes_audio():
    audio = _stereo_test_tone()
    source_level = measure_audio_level_db(audio)

    neutral = apply_live_mastering(
        audio,
        MasteringControls(target_lufs=source_level, auto_eq=False, true_peak_limiter=True),
        source_level_db=source_level,
    )
    auto_eq = apply_live_mastering(
        audio,
        MasteringControls(target_lufs=source_level, auto_eq=True, true_peak_limiter=True),
        source_level_db=source_level,
    )

    assert np.max(np.abs(auto_eq - neutral)) >= 0.02
    assert np.max(np.abs(auto_eq)) <= 0.99


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
