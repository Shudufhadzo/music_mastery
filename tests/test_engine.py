from pathlib import Path

from mastery_native.engine import (
    MasteringControls,
    build_loudness_match_gains,
    build_output_paths,
    build_preview_output_paths,
    hidden_subprocess_kwargs,
    reference_strength_weights,
    save_mastered_previews,
    styled_controls,
)
from mastery_native.toolchain import resolve_ffmpeg_path


def test_build_output_paths_appends_master_suffix_and_wav_extension():
    outputs = build_output_paths(
        [r"C:\music\one.wav", r"C:\music\two.mp3"],
        r"C:\exports",
    )

    assert outputs == [
        r"C:\exports\one-master.wav",
        r"C:\exports\two-master.wav",
    ]


def test_build_preview_output_paths_uses_preview_suffix():
    outputs = build_preview_output_paths(
        [r"C:\music\one.wav", r"C:\music\two.mp3"],
        r"C:\temp\preview",
    )

    assert outputs == [
        r"C:\temp\preview\one-master-preview.wav",
        r"C:\temp\preview\two-master-preview.wav",
    ]


def test_manual_pre_filter_uses_current_control_values():
    controls = MasteringControls(
        gain_db=1.5,
        clarity_percent=75,
        bass_percent=70,
        treble_percent=65,
        punch_percent=80,
        stereo_width_percent=70,
        low_cut_hz=32,
        high_cut_hz=17000,
        auto_eq=True,
    )

    filter_graph = controls.manual_pre_filter()

    assert "highpass=f=32" in filter_graph
    assert "bass=g=2.4:f=100:w=0.8" in filter_graph
    assert "equalizer=f=2500:t=q:w=1.2:g=2.0" in filter_graph
    assert "treble=g=1.5:f=4500:w=0.6" in filter_graph
    assert "acompressor=" in filter_graph
    assert "volume=1.5dB" in filter_graph
    assert "extrastereo=m=1.20" in filter_graph


def test_resolve_ffmpeg_path_prefers_explicit_env_var(tmp_path: Path, monkeypatch):
    ffmpeg_path = tmp_path / "ffmpeg.exe"
    ffmpeg_path.write_text("stub", encoding="utf-8")
    monkeypatch.setenv("FFMPEG_PATH", str(ffmpeg_path))

    assert resolve_ffmpeg_path() == str(ffmpeg_path)


def test_save_mastered_previews_copies_temp_preview_to_final_output(tmp_path: Path):
    preview_file = tmp_path / "preview" / "one-master-preview.wav"
    preview_file.parent.mkdir(parents=True)
    preview_file.write_bytes(b"preview-data")

    saved_paths = save_mastered_previews(
        preview_paths=[str(preview_file)],
        source_paths=[r"C:\music\one.wav"],
        output_directory=str(tmp_path / "exports"),
    )

    assert saved_paths == [str(tmp_path / "exports" / "one-master.wav")]
    assert (tmp_path / "exports" / "one-master.wav").read_bytes() == b"preview-data"


def test_hidden_subprocess_kwargs_hide_windows_console():
    kwargs = hidden_subprocess_kwargs()

    assert "creationflags" in kwargs
    assert kwargs["creationflags"] != 0
    assert "startupinfo" in kwargs


def test_styled_controls_applies_warm_preset_with_intensity():
    controls = styled_controls("Warm", 50)

    assert controls.clarity_percent < 50
    assert controls.bass_percent > 50
    assert controls.treble_percent < 50
    assert controls.target_lufs > -14.0


def test_build_loudness_match_gains_reduces_louder_version():
    original_gain, mastered_gain = build_loudness_match_gains(-15.0, -9.0)

    assert original_gain == 1.0
    assert round(mastered_gain, 2) == 0.5


def test_reference_strength_weights_favor_original_at_lower_strength():
    original_weight, mastered_weight = reference_strength_weights(25)

    assert round(original_weight, 2) == 0.75
    assert round(mastered_weight, 2) == 0.25
