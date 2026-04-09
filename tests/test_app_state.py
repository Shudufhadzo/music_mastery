from mastery_native.app_state import MasteringSessionState


def test_add_tracks_respects_existing_queue_limit():
    state = MasteringSessionState(track_paths=[rf"C:\music\existing-{index}.wav" for index in range(8)])

    result = state.add_tracks(
        [
            r"C:\music\new-1.wav",
            r"C:\music\new-2.mp3",
            r"C:\music\new-3.flac",
            r"C:\music\new-4.wav",
        ]
    )

    assert state.track_paths == [
        r"C:\music\existing-0.wav",
        r"C:\music\existing-1.wav",
        r"C:\music\existing-2.wav",
        r"C:\music\existing-3.wav",
        r"C:\music\existing-4.wav",
        r"C:\music\existing-5.wav",
        r"C:\music\existing-6.wav",
        r"C:\music\existing-7.wav",
        r"C:\music\new-1.wav",
        r"C:\music\new-2.mp3",
    ]
    assert result.added == [r"C:\music\new-1.wav", r"C:\music\new-2.mp3"]
    assert result.limit_reached is True


def test_add_tracks_reports_duplicates_and_invalid_files():
    state = MasteringSessionState(track_paths=[r"C:\music\one.wav"])

    result = state.add_tracks(
        [
            r"C:\music\one.wav",
            r"C:\music\cover.png",
            r"C:\music\two.mp3",
        ]
    )

    assert state.track_paths == [r"C:\music\one.wav", r"C:\music\two.mp3"]
    assert result.added == [r"C:\music\two.mp3"]
    assert result.duplicates == [r"C:\music\one.wav"]
    assert result.invalid == [r"C:\music\cover.png"]


def test_set_reference_track_accepts_supported_audio():
    state = MasteringSessionState()

    accepted = state.set_reference_track(r"C:\music\reference.mp3")

    assert accepted is True
    assert state.reference_track_path == r"C:\music\reference.mp3"


def test_set_reference_track_rejects_unsupported_audio():
    state = MasteringSessionState()

    accepted = state.set_reference_track(r"C:\music\reference.png")

    assert accepted is False
    assert state.reference_track_path is None


def test_register_preview_outputs_builds_original_and_mastered_pairs():
    state = MasteringSessionState(track_paths=[r"C:\music\one.wav", r"C:\music\two.mp3"])

    state.register_preview_outputs(
        [
            r"C:\temp\one-master-preview.wav",
            r"C:\temp\two-master-preview.wav",
        ]
    )

    assert [pair.original_path for pair in state.preview_pairs] == [
        r"C:\music\one.wav",
        r"C:\music\two.mp3",
    ]
    assert [pair.mastered_preview_path for pair in state.preview_pairs] == [
        r"C:\temp\one-master-preview.wav",
        r"C:\temp\two-master-preview.wav",
    ]
    assert state.has_preview_results is True


def test_adding_tracks_clears_old_preview_pairs():
    state = MasteringSessionState(track_paths=[r"C:\music\one.wav"])
    state.register_preview_outputs([r"C:\temp\one-master-preview.wav"])

    state.add_tracks([r"C:\music\two.wav"])

    assert state.preview_pairs == []
    assert state.has_preview_results is False
