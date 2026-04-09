from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac"}
AUDIO_FILE_DIALOG_FILTER = "Audio files (*.wav *.mp3 *.flac)"


def normalize_path(raw_path: str) -> str:
    return os.path.normpath(str(Path(raw_path)))


def dedupe_key(raw_path: str) -> str:
    return os.path.normcase(normalize_path(raw_path))


def is_supported_audio_path(raw_path: str) -> bool:
    return Path(normalize_path(raw_path)).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS


def accepted_audio_paths(
    paths: Iterable[str],
    *,
    max_items: int = 10,
    existing_paths: Iterable[str] = (),
) -> list[str]:
    accepted: list[str] = []
    seen = {dedupe_key(path) for path in existing_paths}

    for raw_path in paths:
        normalized = normalize_path(raw_path)
        key = dedupe_key(normalized)

        if not is_supported_audio_path(normalized) or key in seen:
            continue

        accepted.append(normalized)
        seen.add(key)

        if len(accepted) >= max_items:
            break

    return accepted


def build_manual_mastering_command(
    *,
    ffmpeg_normalize_path: str,
    inputs: list[str],
    outputs: list[str],
    target_lufs: float,
    album_mode: bool,
    pre_filter: str,
) -> list[str]:
    command = [
        ffmpeg_normalize_path,
        *inputs,
        "-o",
        *outputs,
        "-f",
    ]

    if album_mode and len(inputs) > 1:
        command.append("--batch")

    command.extend(
        [
            "-nt",
            "ebu",
            "-t",
            f"{target_lufs:.1f}",
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
            pre_filter,
        ]
    )

    return command


def build_reference_match_command(
    *,
    python_path: str,
    matchering_script: str,
    target_track: str,
    reference_track: str,
    output_track: str,
    bit_depth: int,
    limiter_enabled: bool,
) -> list[str]:
    command = [
        python_path,
        matchering_script,
        "-b",
        str(bit_depth),
        target_track,
        reference_track,
        output_track,
    ]

    if not limiter_enabled:
        command.insert(4, "--no_limiter")

    return command
