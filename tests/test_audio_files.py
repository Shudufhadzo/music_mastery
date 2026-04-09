from mastery_native.audio_files import (
    AUDIO_FILE_DIALOG_FILTER,
    SUPPORTED_AUDIO_EXTENSIONS,
    accepted_audio_paths,
    is_supported_audio_path,
    build_manual_mastering_command,
    build_reference_match_command,
)


def test_supported_audio_extensions_are_locked_down():
    assert SUPPORTED_AUDIO_EXTENSIONS == {".wav", ".mp3", ".flac"}


def test_accepts_supported_audio_files_only_and_deduplicates():
    files = [
        r"C:\music\one.wav",
        r"C:\music\two.mp3",
        r"C:\music\three.flac",
        r"C:\music\one.wav",
        r"C:\music\cover.png",
        r"C:\music\notes.txt",
    ]

    assert accepted_audio_paths(files) == [
        r"C:\music\one.wav",
        r"C:\music\two.mp3",
        r"C:\music\three.flac",
    ]


def test_accepts_uppercase_audio_extensions():
    files = [
        r"C:\music\one.WAV",
        r"C:\music\two.MP3",
        r"C:\music\three.FlAc",
    ]

    assert accepted_audio_paths(files) == files


def test_deduplicates_case_insensitive_windows_paths():
    files = [
        r"C:\Music\One.WAV",
        r"c:\music\one.wav",
        r"C:\MUSIC\ONE.wav",
    ]

    assert accepted_audio_paths(files) == [r"C:\Music\One.WAV"]


def test_caps_track_imports_at_ten_files():
    files = [rf"C:\music\track-{index}.wav" for index in range(12)]

    assert len(accepted_audio_paths(files)) == 10


def test_builds_expected_audio_file_dialog_filter():
    assert AUDIO_FILE_DIALOG_FILTER == "Audio files (*.wav *.mp3 *.flac)"


def test_checks_supported_audio_path_by_extension():
    assert is_supported_audio_path(r"C:\music\mix.wav") is True
    assert is_supported_audio_path(r"C:\music\mix.mp3") is True
    assert is_supported_audio_path(r"C:\music\cover.jpg") is False


def test_builds_manual_mastering_command_for_album_run():
    command = build_manual_mastering_command(
        ffmpeg_normalize_path=r"C:\tools\ffmpeg-normalize.exe",
        inputs=[r"C:\audio\one.wav", r"C:\audio\two.mp3"],
        outputs=[r"C:\out\one.wav", r"C:\out\two.wav"],
        target_lufs=-11.5,
        album_mode=True,
        pre_filter="highpass=f=28,deesser=i=0.10",
    )

    assert command == [
        r"C:\tools\ffmpeg-normalize.exe",
        r"C:\audio\one.wav",
        r"C:\audio\two.mp3",
        "-o",
        r"C:\out\one.wav",
        r"C:\out\two.wav",
        "-f",
        "--batch",
        "-nt",
        "ebu",
        "-t",
        "-11.5",
        "-tp",
        "-1",
        "-lrt",
        "9",
        "--dynamic",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        "-ext",
        "wav",
        "-prf",
        "highpass=f=28,deesser=i=0.10",
    ]


def test_builds_reference_match_command():
    command = build_reference_match_command(
        python_path=r"C:\tools\python.exe",
        matchering_script=r"C:\tools\mg_cli.py",
        target_track=r"C:\audio\target.wav",
        reference_track=r"C:\audio\reference.wav",
        output_track=r"C:\out\master.wav",
        bit_depth=24,
        limiter_enabled=True,
    )

    assert command == [
        r"C:\tools\python.exe",
        r"C:\tools\mg_cli.py",
        "-b",
        "24",
        r"C:\audio\target.wav",
        r"C:\audio\reference.wav",
        r"C:\out\master.wav",
    ]
