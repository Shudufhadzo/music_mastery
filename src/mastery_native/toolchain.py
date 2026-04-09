from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def bundled_ffmpeg_path() -> str | None:
    executable_dir = Path(sys.executable).resolve().parent
    candidates = [
        executable_dir / "ffmpeg.exe",
        executable_dir / "tools" / "ffmpeg" / "ffmpeg.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def winget_ffmpeg_path() -> str | None:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local_app_data:
        return None

    packages_dir = local_app_data / "Microsoft" / "WinGet" / "Packages"
    patterns = [
        "Gyan.FFmpeg_*\\ffmpeg-*\\bin\\ffmpeg.exe",
        "Gyan.FFmpeg*\\ffmpeg-*\\bin\\ffmpeg.exe",
    ]

    for pattern in patterns:
        matches = sorted(packages_dir.glob(pattern), reverse=True)
        if matches:
            return str(matches[0])

    return None


def resolve_ffmpeg_path() -> str:
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    executable = shutil.which("ffmpeg")
    if executable:
        return executable

    bundled = bundled_ffmpeg_path()
    if bundled:
        return bundled

    winget_path = winget_ffmpeg_path()
    if winget_path:
        return winget_path

    raise FileNotFoundError("FFmpeg was not found. Install FFmpeg or bundle ffmpeg.exe with the app.")
