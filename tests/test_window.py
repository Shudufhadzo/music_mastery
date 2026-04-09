import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QBoxLayout

from mastery_native.engine import MasteringControls
from mastery_native.live_audio import LiveAudioTrack, build_waveform_peaks, measure_audio_level_db
from mastery_native.preset_store import MasteringPresetStore
from mastery_native.window import MasteryWindow, create_application


def _fake_live_track(path: str) -> LiveAudioTrack:
    timeline = np.linspace(0, 0.2, 4410, endpoint=False)
    left = 0.2 * np.sin(2 * np.pi * 220 * timeline)
    right = 0.2 * np.sin(2 * np.pi * 330 * timeline)
    audio = np.column_stack([left, right]).astype(np.float32)
    waveform = build_waveform_peaks(audio)
    return LiveAudioTrack(
        path=path,
        sample_rate=44100,
        original_audio=audio,
        mastered_audio=audio.copy(),
        original_waveform=waveform,
        mastered_waveform=list(waveform),
        source_level_db=measure_audio_level_db(audio),
    )


def _show_window(window: MasteryWindow) -> None:
    window.show()
    QTest.qWait(50)


def test_window_starts_on_music_mastery_home_screen(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    assert window.audio_file_filter == "Audio files (*.wav *.mp3 *.flac)"
    assert window.windowTitle() == "Music Mastery"
    assert window.brand_name_label.text() == "Music Mastery"
    assert window.content_stack.currentWidget() is window.home_page
    assert window.home_title_label.text() == "Professional mastering made simple"
    assert window.home_reference_button.text() == "Match a Reference"
    assert window.home_manual_button.text() == "Manual Controls"
    assert window.sidebar.isHidden() is True
    assert window.back_button.isHidden() is True
    assert window.status_label.isHidden() is True


def test_window_manual_workspace_uses_stepper_and_compare_surface(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=False)

    assert window.content_stack.currentWidget() is window.workspace_page
    assert window.back_button.isHidden() is False
    assert window.sidebar.isHidden() is False
    assert [label.text() for label in window.step_labels] == ["Upload", "Adjust", "Compare"]
    assert window.sidebar_heading.text() == "Mastering"
    assert window.original_title_label.text() == "Original"
    assert window.mastered_title_label.text() == "Mastered"
    assert window.original_listen_button.text() == "A"
    assert window.mastered_listen_button.text() == "B"
    assert window.download_button.text() == "Export"
    assert window.revert_button.text() == "Reset"
    assert window.compare_heading_label.isHidden() is True
    assert window.manual_section_detail.isHidden() is True
    assert window.manual_track_zone.detail_label.isHidden() is True
    assert window.main_panel_scroll.widget() is window.main_panel
    assert window.main_panel_scroll.viewport().autoFillBackground() is False
    assert window.sidebar_scroll.widget() is window.manual_controls_container
    assert window.manual_controls_container.objectName() == "manualControlsCanvas"
    assert window.manual_controls_container.autoFillBackground() is False
    assert window.sidebar_scroll.viewport().autoFillBackground() is False


def test_window_exposes_beginner_labels_and_tooltips_for_mastering_controls(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=False)

    assert window.control_text_labels["gain_db"].text() == "Volume"
    assert window.control_text_labels["target_lufs"].text() == "Target Loudness"
    assert window.control_text_labels["clarity_percent"].text() == "Clarity"
    assert window.control_text_labels["bass_percent"].text() == "Bass"
    assert window.control_text_labels["treble_percent"].text() == "Treble"
    assert window.control_text_labels["punch_percent"].text() == "Punch"
    assert window.control_text_labels["stereo_width_percent"].text() == "Stereo Width"
    assert window.control_text_labels["low_cut_hz"].text() == "Low Cut"
    assert window.control_text_labels["high_cut_hz"].text() == "High Cut"
    assert window.control_info_buttons["gain_db"].toolTip() == "Higher plays the master louder."
    assert window.control_info_buttons["target_lufs"].toolTip() == "Higher makes the finished song louder."
    assert window.control_info_buttons["clarity_percent"].toolTip() == "Higher makes vocals and lead parts clearer."
    assert window.control_info_buttons["bass_percent"].toolTip() == "Higher adds more bass and weight."
    assert window.control_info_buttons["treble_percent"].toolTip() == "Higher adds more shine and air."
    assert window.control_info_buttons["punch_percent"].toolTip() == "Higher makes drums hit harder."
    assert window.control_info_buttons["stereo_width_percent"].toolTip() == "Higher makes the song feel wider."
    assert window.control_info_buttons["low_cut_hz"].toolTip() == "Higher removes more low bass and rumble."
    assert window.control_info_buttons["high_cut_hz"].toolTip() == "Lower softens the bright top end."
    assert window.control_info_buttons["true_peak_limiter"].toolTip() == "On keeps loud peaks under control."
    assert window.control_info_buttons["auto_eq"].toolTip() == "On gently balances the tone for you."


def test_window_reference_workspace_hides_manual_sidebar_and_shows_reference_flow(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=True)

    assert window.content_stack.currentWidget() is window.workspace_page
    assert [label.text() for label in window.step_labels] == ["Reference", "Your Track", "Compare"]
    assert window.sidebar.isHidden() is True
    assert window.reference_zone.isHidden() is False
    assert window.reference_track_zone.isHidden() is False
    assert window.reference_apply_button.text() == "Apply"
    assert window.reference_strength_slider.isHidden() is False
    assert window.reference_section_detail_left.isHidden() is True
    assert window.reference_section_detail_right.isHidden() is True
    assert window.reference_zone.detail_label.isHidden() is True
    assert window.reference_track_zone.detail_label.isHidden() is True


def test_window_switches_workspace_layout_for_narrow_width(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=False)
    window.setMinimumSize(0, 0)
    window.resize(1160, 860)
    window._update_responsive_layouts()

    assert window.workspace_layout.direction() == QBoxLayout.Direction.TopToBottom


def test_window_keeps_side_by_side_layout_for_wide_width(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=False)
    window.resize(1760, 980)
    window._update_responsive_layouts()

    assert window.workspace_layout.direction() == QBoxLayout.Direction.LeftToRight


def test_window_import_tracks_replaces_current_track_and_enables_shared_transport(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"track")

    window.import_tracks(
        [
            str(track_path),
            r"C:\music\cover.png",
        ]
    )

    assert window.session_state.track_paths == [str(track_path)]
    assert window.track_name_chip.text() == "one.wav"
    assert window.original_upload_button.isHidden() is False
    assert window.original_upload_button.text() == "Replace Track"
    assert window.transport_play_button.isEnabled() is True
    assert window.transport_stop_button.isEnabled() is False
    assert window.original_listen_button.isEnabled() is True
    assert window.mastered_listen_button.isEnabled() is True
    assert "one.wav" in window.original_waveform.display_text()
    assert window.status_label.text() == "Track loaded"


def test_window_replacing_track_clears_preview_and_transport(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    first_track = tmp_path / "one.wav"
    first_track.write_bytes(b"one")
    second_track = tmp_path / "two.mp3"
    second_track.write_bytes(b"two")
    window.import_tracks([str(first_track)])
    window._set_active_source("mastered")
    window.transport_state = "playing"
    window._sync_transport_buttons()

    window.import_tracks([str(second_track)])

    assert window.session_state.track_paths == [str(second_track)]
    assert window.session_state.has_preview_results is False
    assert window.track_name_chip.text() == "two.mp3"
    assert window.original_upload_button.text() == "Replace Track"
    assert window.mastered_file_label.text() == "two.mp3"
    assert window.transport_play_button.text() == "Play"
    assert window.original_listen_button.isChecked() is True
    assert window.status_label.text() == "Track loaded"


def test_window_import_reference_track_updates_status(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window.import_reference_tracks([r"C:\music\reference.flac"])

    assert window.session_state.reference_track_path == r"C:\music\reference.flac"
    assert window.status_label.text() == "Track loaded"
    assert window.reference_zone.empty_state_label.text() == "reference.flac"


def test_window_rejects_invalid_reference_track(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window.import_reference_tracks([r"C:\music\cover.png"])

    assert window.session_state.reference_track_path is None
    assert window.status_label.text() == "Unsupported track"


def test_window_manual_mode_reveals_manual_controls(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._sync_mode_ui(reference_mode=False)

    assert window.manual_controls_container.isHidden() is False
    assert window.undo_button.isHidden() is False
    assert window.apply_changes_button.isHidden() is True
    assert window.reference_controls_container.isHidden() is True


def test_window_reference_mode_shows_reference_strength_only(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    assert window.reference_controls_container.isHidden() is False
    assert window.reference_strength_value_label.text() == "100%"
    assert window.manual_controls_container.isHidden() is True


def test_window_apply_completion_exposes_reference_master_and_download(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    monkeypatch.setattr("mastery_native.window.decode_audio_file", lambda path, sample_rate=44100: _fake_live_track(path).original_audio)
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    reference_path = tmp_path / "reference.wav"
    reference_path.write_bytes(b"ref")
    window.import_reference_tracks([str(reference_path)])
    window.import_tracks([str(track_path)])
    preview_path = tmp_path / "one-master-preview.wav"
    preview_path.write_bytes(b"preview")

    window._on_mastering_completed([str(preview_path)])

    assert window.mastered_title_label.text() == "Mastered"
    assert window.mastered_file_label.text() == "one-master-preview.wav"
    assert window.transport_play_button.isEnabled() is True
    assert window.download_button.isHidden() is False
    assert window.status_label.text() == "Preview ready"


def test_window_revert_clears_preview_and_returns_to_original_only(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    monkeypatch.setattr("mastery_native.window.decode_audio_file", lambda path, sample_rate=44100: _fake_live_track(path).original_audio)
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window.import_tracks([str(track_path)])
    preview_path = tmp_path / "one-master-preview.wav"
    preview_path.write_bytes(b"preview")
    window._on_mastering_completed([str(preview_path)])

    window.revert_preview()

    assert window.session_state.has_preview_results is False
    assert window.mastered_file_label.text() == "one.wav"
    assert window.transport_play_button.isEnabled() is True
    assert window.status_label.text() == "Reverted"


def test_window_undo_restores_last_committed_controls(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window._update_control("bass_percent", 72)
    window._update_control("target_lufs", -9.0)

    window.undo_control_changes()

    assert window.controls.bass_percent == 50
    assert window.controls.target_lufs == -14.0
    assert window.control_value_labels["bass_percent"].text() == "50%"
    assert window.control_value_labels["target_lufs"].text() == "-14 LUFS"


def test_window_save_and_load_memory_round_trip(tmp_path, monkeypatch):
    create_application()
    store = MasteringPresetStore(tmp_path / "presets.json")
    window = MasteryWindow(preset_store=store)

    window._apply_controls(MasteringControls(gain_db=7.0, clarity_percent=62), announce=False)
    monkeypatch.setattr(
        "mastery_native.window.QInputDialog.getText",
        lambda *args, **kwargs: ("Club Lift", True),
    )

    window.save_current_memory()

    assert "Club Lift" in [window.memory_combo.itemText(i) for i in range(window.memory_combo.count())]
    assert store.load_preset("Club Lift").gain_db == 7.0

    window._apply_controls(MasteringControls(gain_db=0.0, clarity_percent=50), announce=False)
    window.memory_combo.setCurrentText("Club Lift")
    window.load_selected_memory()

    assert window.controls.gain_db == 7.0
    assert window.controls.clarity_percent == 62


def test_window_style_preset_updates_controls(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    window._sync_mode_ui(reference_mode=False)

    window.style_combo.setCurrentText("Vocal")
    window.style_intensity_slider.setValue(80)

    assert window.controls.clarity_percent > 50
    assert window.controls.treble_percent > 50
    assert window.controls.punch_percent >= 50
    assert window.style_intensity_value_label.text() == "80%"


def test_window_style_preset_preserves_loaded_master_level(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window._sync_mode_ui(reference_mode=False)
    window.import_tracks([str(track_path)])
    baseline_level = window.controls.target_lufs

    window.style_combo.setCurrentText("Warm")
    window.style_intensity_slider.setValue(75)

    assert window.controls.target_lufs == baseline_level


def test_window_importing_multiple_tracks_enables_album_selector(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))

    window.import_tracks([r"C:\music\one.wav", r"C:\music\two.mp3", r"C:\music\three.flac"])

    assert window.session_state.track_paths == [
        r"C:\music\one.wav",
        r"C:\music\two.mp3",
        r"C:\music\three.flac",
    ]
    assert window.track_name_chip.text() == "Album - 3 Tracks"
    assert window.track_selector.isHidden() is False
    assert window.track_selector.count() == 3


def test_window_album_selector_switches_preview_target(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    window.import_tracks([r"C:\music\one.wav", r"C:\music\two.mp3"])
    window._on_mastering_completed(
        [
            r"C:\temp\one-master-preview.wav",
            r"C:\temp\two-master-preview.wav",
        ]
    )

    window.track_selector.setCurrentIndex(1)

    assert window.original_file_label.text() == "two.mp3"
    assert window.mastered_file_label.text() == "two-master-preview.wav"


def test_window_switching_active_source_updates_listen_state(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window.import_tracks([str(track_path)])

    window._set_active_source("mastered")

    assert window.mastered_listen_button.isChecked() is True
    assert window.original_listen_button.isChecked() is False

    window._set_active_source("original")

    assert window.original_listen_button.isChecked() is True
    assert window.mastered_listen_button.isChecked() is False


def test_window_seek_slider_updates_playhead_and_audio_position(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window.import_tracks([str(track_path)])

    window.position_slider.setValue(500)

    assert 0.49 <= window.original_waveform.playhead_progress() <= 0.51
    assert 0.49 <= window.mastered_waveform.playhead_progress() <= 0.51
    assert window.audio_device.current_position() > 0


def test_window_shared_transport_cycles_play_pause_resume_stop(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window.import_tracks([str(track_path)])
    monkeypatch.setattr(window.audio_sink, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "suspend", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "resume", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "stop", lambda *args, **kwargs: None)

    window.toggle_transport_playback()

    assert window.transport_play_button.text() == "Pause"
    assert window.transport_stop_button.isEnabled() is True

    window.toggle_transport_playback()

    assert window.transport_play_button.text() == "Resume"

    window.toggle_transport_playback()

    assert window.transport_play_button.text() == "Pause"

    window.stop_transport()

    assert window.transport_play_button.text() == "Play"
    assert window.transport_stop_button.isEnabled() is False


def test_window_escape_returns_home_and_stops_transport(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    _show_window(window)
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window._sync_mode_ui(reference_mode=False)
    window.import_tracks([str(track_path)])
    monkeypatch.setattr(window.audio_sink, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "stop", lambda *args, **kwargs: None)

    window.toggle_transport_playback()
    window.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Escape)

    assert window.content_stack.currentWidget() is window.home_page
    assert window.transport_state == "stopped"
    assert window.back_button.isHidden() is True


def test_window_space_toggles_transport_from_window_focus(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    _show_window(window)
    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    track_path = tmp_path / "one.wav"
    track_path.write_bytes(b"one")
    window._sync_mode_ui(reference_mode=False)
    window.import_tracks([str(track_path)])
    monkeypatch.setattr(window.audio_sink, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "suspend", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "resume", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "stop", lambda *args, **kwargs: None)

    window.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.transport_state == "playing"

    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.transport_state == "paused"

    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.transport_state == "playing"


def test_window_tab_order_prioritizes_primary_manual_actions(tmp_path):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    _show_window(window)
    window._sync_mode_ui(reference_mode=False)

    window.original_upload_button.setFocus()
    assert window.focusWidget() is window.original_upload_button

    QTest.keyClick(window.original_upload_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.quick_preset_buttons["Warm"]

    QTest.keyClick(window.quick_preset_buttons["Warm"], Qt.Key.Key_Tab)
    assert window.focusWidget() is window.save_memory_button

    QTest.keyClick(window.save_memory_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.undo_button


def test_window_manual_flow_end_to_end_with_keyboard_and_memory(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    _show_window(window)
    track_path = tmp_path / "club.wav"
    track_path.write_bytes(b"track")
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    exported = {}

    monkeypatch.setattr("mastery_native.window.load_live_audio_track", lambda path: _fake_live_track(path))
    monkeypatch.setattr(
        "mastery_native.window.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(track_path)], window.audio_file_filter),
    )
    monkeypatch.setattr(
        "mastery_native.window.QInputDialog.getText",
        lambda *args, **kwargs: ("Club Lift", True),
    )
    monkeypatch.setattr(
        "mastery_native.window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(export_dir),
    )
    monkeypatch.setattr(window.audio_sink, "start", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "suspend", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "resume", lambda *args, **kwargs: None)
    monkeypatch.setattr(window.audio_sink, "stop", lambda *args, **kwargs: None)

    def _fake_write(path, data, sample_rate, subtype=None):
        exported["path"] = path
        exported["sample_rate"] = sample_rate
        exported["subtype"] = subtype

    monkeypatch.setattr("soundfile.write", _fake_write)

    window.home_manual_button.setFocus()
    QTest.keyClick(window.home_manual_button, Qt.Key.Key_Return)
    assert window.content_stack.currentWidget() is window.workspace_page

    window.original_upload_button.setFocus()
    QTest.keyClick(window.original_upload_button, Qt.Key.Key_Return)
    assert window.track_name_chip.text() == "club.wav"

    window.control_sliders["bass_percent"].setValue(72)
    window.save_memory_button.setFocus()
    QTest.keyClick(window.save_memory_button, Qt.Key.Key_Return)
    assert "Club Lift" in [window.memory_combo.itemText(i) for i in range(window.memory_combo.count())]

    window.control_sliders["bass_percent"].setValue(40)
    assert window.memory_combo.currentText() == "Memories"
    window.memory_combo.setCurrentText("Club Lift")
    assert window.controls.bass_percent == 72

    window.transport_play_button.setFocus()
    QTest.keyClick(window.transport_play_button, Qt.Key.Key_Return)
    assert window.transport_state == "playing"

    window.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Space)
    assert window.transport_state == "paused"

    window.mastered_listen_button.setFocus()
    QTest.keyClick(window.mastered_listen_button, Qt.Key.Key_Return)
    assert window.active_source == "mastered"

    window.download_button.setFocus()
    QTest.keyClick(window.download_button, Qt.Key.Key_Return)
    assert exported["path"].endswith("club-master.wav")
    assert exported["sample_rate"] == 44100
    assert exported["subtype"] == "PCM_16"

    window.setFocus()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert window.content_stack.currentWidget() is window.home_page
    assert window.transport_state == "stopped"


def test_window_reference_flow_end_to_end_with_keyboard(tmp_path, monkeypatch):
    create_application()
    window = MasteryWindow(preset_store=MasteringPresetStore(tmp_path / "presets.json"))
    _show_window(window)
    reference_path = tmp_path / "reference.wav"
    reference_path.write_bytes(b"ref")
    track_path = tmp_path / "target.wav"
    track_path.write_bytes(b"track")
    preview_path = tmp_path / "target-master-preview.wav"
    preview_path.write_bytes(b"preview")

    monkeypatch.setattr(
        "mastery_native.window.load_live_audio_track",
        lambda path: _fake_live_track(path),
    )
    monkeypatch.setattr(
        "mastery_native.window.decode_audio_file",
        lambda path, sample_rate=44100: _fake_live_track(path).original_audio,
    )
    monkeypatch.setattr(
        "mastery_native.window.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(reference_path), window.audio_file_filter),
    )
    monkeypatch.setattr(
        "mastery_native.window.QFileDialog.getOpenFileNames",
        lambda *args, **kwargs: ([str(track_path)], window.audio_file_filter),
    )

    class _DummySignal:
        def __init__(self):
            self._handlers = []

        def connect(self, handler):
            self._handlers.append(handler)

        def emit(self, *args):
            for handler in list(self._handlers):
                handler(*args)

    class _DummyWorker:
        def __init__(self, **kwargs):
            self.completed = _DummySignal()
            self.failed = _DummySignal()

        def start(self):
            self.completed.emit([str(preview_path)])

    monkeypatch.setattr("mastery_native.window.MasteringWorker", _DummyWorker)

    window.home_reference_button.setFocus()
    QTest.keyClick(window.home_reference_button, Qt.Key.Key_Return)
    assert window.content_stack.currentWidget() is window.workspace_page

    window.reference_zone.select_button.setFocus()
    QTest.keyClick(window.reference_zone.select_button, Qt.Key.Key_Return)
    assert window.session_state.reference_track_path == str(reference_path)

    window.reference_track_zone.select_button.setFocus()
    QTest.keyClick(window.reference_track_zone.select_button, Qt.Key.Key_Return)
    assert window.track_name_chip.text() == "target.wav"

    window.reference_apply_button.setFocus()
    QTest.keyClick(window.reference_apply_button, Qt.Key.Key_Return)

    assert window.session_state.has_preview_results is True
    assert window.mastered_file_label.text() == "target-master-preview.wav"
    assert window.status_label.text() == "Preview ready"
