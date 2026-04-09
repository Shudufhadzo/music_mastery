from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mastery_native.toolchain import resolve_ffmpeg_path

LOGGER = logging.getLogger(__name__)


def hidden_subprocess_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    if hasattr(subprocess, "SW_HIDE"):
        startupinfo.wShowWindow = subprocess.SW_HIDE

    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def patch_silent_audio_subprocesses() -> None:
    _patch_ffmpeg_normalize_subprocesses()
    _patch_matchering_subprocesses()


def _patch_ffmpeg_normalize_subprocesses() -> None:
    import shlex

    import ffmpeg_normalize._cmd_utils as cmd_utils
    from ffmpeg_progress_yield import FfmpegProgress

    if getattr(cmd_utils, "_mastery_no_window_patch", False):
        return

    def run_ffmpeg_command(self, cmd: list[str]):
        cmd_utils._logger.debug(f"Running command: {shlex.join(cmd)}")
        with FfmpegProgress(cmd, dry_run=self.dry) as ff:
            yield from ff.run_command_with_progress(
                popen_kwargs={
                    "env": cmd_utils._get_ffmpeg_env(),
                    **hidden_subprocess_kwargs(),
                }
            )
            self.output = ff.stderr

        if cmd_utils._logger.getEffectiveLevel() == logging.DEBUG and self.output is not None:
            cmd_utils._logger.debug(
                f"ffmpeg output: {cmd_utils.CommandRunner.prune_ffmpeg_progress_from_output(self.output)}"
            )

    def run_command(self, cmd: list[str]):
        cmd_utils._logger.debug(f"Running command: {shlex.join(cmd)}")

        if self.dry:
            cmd_utils._logger.debug("Dry mode specified, not actually running command")
            return self

        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
            env=cmd_utils._get_ffmpeg_env(),
            **hidden_subprocess_kwargs(),
        )

        stdout_bytes, stderr_bytes = process.communicate()
        stdout = stdout_bytes.decode("utf8", errors="replace")
        stderr = stderr_bytes.decode("utf8", errors="replace")

        if process.returncode != 0:
            raise RuntimeError(f"Error running command {shlex.join(cmd)}: {stderr}")

        self.output = stdout + stderr
        return self

    cmd_utils.CommandRunner.run_ffmpeg_command = run_ffmpeg_command
    cmd_utils.CommandRunner.run_command = run_command
    cmd_utils._mastery_no_window_patch = True


def _patch_matchering_subprocesses() -> None:
    import matchering.loader as loader

    if getattr(loader, "_mastery_no_window_patch", False):
        return

    original_check_call = loader.subprocess.check_call

    def quiet_check_call(*args, **kwargs):
        return original_check_call(*args, **{**hidden_subprocess_kwargs(), **kwargs})

    loader.subprocess.check_call = quiet_check_call
    loader._mastery_no_window_patch = True


@dataclass(slots=True)
class MasteringControls:
    gain_db: float = 0.0
    target_lufs: float = -14.0
    clarity_percent: int = 50
    bass_percent: int = 50
    treble_percent: int = 50
    punch_percent: int = 50
    stereo_width_percent: int = 50
    low_cut_hz: int = 20
    high_cut_hz: int = 20000
    true_peak_limiter: bool = True
    auto_eq: bool = False
    bit_depth: int = 24
    reference_strength_percent: int = 100

    def manual_pre_filter(self) -> str:
        filters = [f"highpass=f={int(self.low_cut_hz)}"]

        bass_gain = _centered_gain(self.bass_percent, 6.0)
        if abs(bass_gain) >= 0.1:
            filters.append(f"bass=g={bass_gain:.1f}:f=100:w=0.8")

        vocal_gain = _centered_gain(self.clarity_percent, 4.0)
        if abs(vocal_gain) >= 0.1:
            filters.append(f"equalizer=f=2500:t=q:w=1.2:g={vocal_gain:.1f}")

        vocal_mud_cut = -max(0.0, (self.clarity_percent - 50) / 50 * 2.0)
        if abs(vocal_mud_cut) >= 0.1:
            filters.append(f"equalizer=f=300:t=q:w=1.0:g={vocal_mud_cut:.1f}")

        treble_gain = _centered_gain(self.treble_percent, 5.0)
        if abs(treble_gain) >= 0.1:
            filters.append(f"treble=g={treble_gain:.1f}:f=4500:w=0.6")

        if self.auto_eq:
            filters.extend(
                [
                    "equalizer=f=180:t=q:w=1.0:g=-1.0",
                    "equalizer=f=4200:t=q:w=1.0:g=1.2",
                ]
            )

        deesser_intensity = min(
            0.24,
            0.03 + (self.clarity_percent / 100 * 0.07) + (max(self.treble_percent - 50, 0) / 50 * 0.04),
        )
        filters.append(f"deesser=i={deesser_intensity:.2f}:m=0.50:f=0.55")

        punch_amount = max(0.0, min(100.0, self.punch_percent)) / 100.0
        threshold = 0.22 - (punch_amount * 0.10)
        ratio = 1.2 + (punch_amount * 1.6)
        makeup = 1.0 + (punch_amount * 0.5)
        filters.append(
            f"acompressor=threshold={threshold:.3f}:ratio={ratio:.2f}:attack=15:release=220:makeup={makeup:.2f}"
        )
        filters.append(f"lowpass=f={int(self.high_cut_hz)}")

        if self.gain_db:
            filters.append(f"volume={self.gain_db:.1f}dB")

        stereo_multiplier = 1.0 + ((self.stereo_width_percent - 50) / 100)
        if round(stereo_multiplier, 2) != 1.0:
            filters.append(f"extrastereo=m={stereo_multiplier:.2f}")

        return ",".join(filters)


@dataclass(slots=True)
class ManualMasteringJob:
    input_paths: list[str]
    output_directory: str
    controls: MasteringControls


@dataclass(slots=True)
class ReferenceMatchJob:
    input_paths: list[str]
    output_directory: str
    reference_track_path: str
    controls: MasteringControls


def _centered_gain(percent: int, max_gain_db: float) -> float:
    clamped = max(0, min(100, percent))
    return ((clamped - 50) / 50) * max_gain_db


STYLE_PRESET_TARGETS = {
    "Clean": MasteringControls(
        target_lufs=-13.0,
        clarity_percent=58,
        bass_percent=48,
        treble_percent=55,
        punch_percent=45,
        stereo_width_percent=54,
        low_cut_hz=32,
        high_cut_hz=18800,
    ),
    "Warm": MasteringControls(
        target_lufs=-12.0,
        clarity_percent=42,
        bass_percent=68,
        treble_percent=38,
        punch_percent=44,
        stereo_width_percent=46,
        low_cut_hz=24,
        high_cut_hz=16800,
    ),
    "Punch": MasteringControls(
        target_lufs=-10.5,
        clarity_percent=56,
        bass_percent=60,
        treble_percent=54,
        punch_percent=82,
        stereo_width_percent=52,
        low_cut_hz=34,
        high_cut_hz=18200,
    ),
    "Wide": MasteringControls(
        target_lufs=-12.0,
        clarity_percent=50,
        bass_percent=52,
        treble_percent=52,
        punch_percent=48,
        stereo_width_percent=78,
        low_cut_hz=30,
        high_cut_hz=18400,
    ),
    "Vocal": MasteringControls(
        target_lufs=-11.5,
        clarity_percent=88,
        bass_percent=44,
        treble_percent=70,
        punch_percent=58,
        stereo_width_percent=58,
        low_cut_hz=40,
        high_cut_hz=19000,
    ),
    "Bright": MasteringControls(
        target_lufs=-12.0,
        clarity_percent=64,
        bass_percent=44,
        treble_percent=78,
        punch_percent=48,
        stereo_width_percent=54,
        low_cut_hz=34,
        high_cut_hz=19600,
    ),
}


def styled_controls(style_name: str, intensity_percent: int) -> MasteringControls:
    base = MasteringControls()
    target = STYLE_PRESET_TARGETS.get(style_name)
    if target is None:
        return base

    mix = max(0.0, min(100.0, intensity_percent)) / 100.0

    def blend(base_value: float, target_value: float) -> float:
        return base_value + (target_value - base_value) * mix

    return MasteringControls(
        gain_db=round(blend(base.gain_db, target.gain_db), 1),
        target_lufs=round(blend(base.target_lufs, target.target_lufs), 1),
        clarity_percent=int(round(blend(base.clarity_percent, target.clarity_percent))),
        bass_percent=int(round(blend(base.bass_percent, target.bass_percent))),
        treble_percent=int(round(blend(base.treble_percent, target.treble_percent))),
        punch_percent=int(round(blend(base.punch_percent, target.punch_percent))),
        stereo_width_percent=int(round(blend(base.stereo_width_percent, target.stereo_width_percent))),
        low_cut_hz=int(round(blend(base.low_cut_hz, target.low_cut_hz))),
        high_cut_hz=int(round(blend(base.high_cut_hz, target.high_cut_hz))),
        true_peak_limiter=target.true_peak_limiter if mix >= 0.5 else base.true_peak_limiter,
        auto_eq=target.auto_eq if mix >= 0.5 else base.auto_eq,
        bit_depth=base.bit_depth,
        reference_strength_percent=base.reference_strength_percent,
    )


def build_loudness_match_gains(original_db: float | None, mastered_db: float | None) -> tuple[float, float]:
    if original_db is None or mastered_db is None:
        return (1.0, 1.0)

    target_db = min(original_db, mastered_db)
    original_gain = min(1.0, max(0.15, math.pow(10.0, (target_db - original_db) / 20.0)))
    mastered_gain = min(1.0, max(0.15, math.pow(10.0, (target_db - mastered_db) / 20.0)))
    return (original_gain, mastered_gain)


def reference_strength_weights(strength_percent: int) -> tuple[float, float]:
    wet = max(0.0, min(100.0, strength_percent)) / 100.0
    dry = 1.0 - wet
    return (dry, wet)


def build_preview_output_paths(input_paths: list[str], output_directory: str) -> list[str]:
    output_root = Path(output_directory)
    return [
        str(output_root / f"{Path(input_path).stem}-master-preview.wav")
        for input_path in input_paths
    ]


def build_output_paths(input_paths: list[str], output_directory: str) -> list[str]:
    output_root = Path(output_directory)
    return [
        str(output_root / f"{Path(input_path).stem}-master.wav")
        for input_path in input_paths
    ]


def analyze_mean_volume_db(path: str) -> float | None:
    ffmpeg_path = resolve_ffmpeg_path()
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-i",
        path,
        "-af",
        "volumedetect",
        "-f",
        "null",
        "NUL" if os.name == "nt" else "/dev/null",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
    if match is None:
        return None
    return float(match.group(1))


def apply_reference_strength_blend(
    *,
    original_path: str,
    mastered_path: str,
    strength_percent: int,
) -> None:
    dry, wet = reference_strength_weights(strength_percent)
    if wet >= 0.999:
        return

    if wet <= 0.001:
        shutil.copy2(original_path, mastered_path)
        return

    ffmpeg_path = resolve_ffmpeg_path()
    temp_output = str(Path(mastered_path).with_suffix(".blend.wav"))
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        original_path,
        "-i",
        mastered_path,
        "-filter_complex",
        (
            f"[0:a]volume={dry:.3f}[dry];"
            f"[1:a]volume={wet:.3f}[wet];"
            "[dry][wet]amix=inputs=2:normalize=0:duration=first,"
            "alimiter=limit=0.97[out]"
        ),
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "44100",
        temp_output,
    ]
    subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
        **hidden_subprocess_kwargs(),
    )
    Path(mastered_path).unlink(missing_ok=True)
    Path(temp_output).replace(mastered_path)


def save_mastered_previews(
    *,
    preview_paths: list[str],
    source_paths: list[str],
    output_directory: str,
) -> list[str]:
    if len(preview_paths) != len(source_paths):
        raise ValueError("Preview and source path counts must match.")

    Path(output_directory).mkdir(parents=True, exist_ok=True)
    saved_paths = build_output_paths(source_paths, output_directory)

    for preview_path, saved_path in zip(preview_paths, saved_paths, strict=True):
        shutil.copy2(preview_path, saved_path)

    return saved_paths


def run_manual_mastering(job: ManualMasteringJob) -> list[str]:
    from ffmpeg_normalize import FFmpegNormalize

    ffmpeg_path = resolve_ffmpeg_path()
    os.environ["FFMPEG_PATH"] = ffmpeg_path
    patch_silent_audio_subprocesses()
    Path(job.output_directory).mkdir(parents=True, exist_ok=True)
    output_paths = build_preview_output_paths(job.input_paths, job.output_directory)

    normalizer = FFmpegNormalize(
        normalization_type="ebu",
        target_level=job.controls.target_lufs,
        loudness_range_target=9,
        true_peak=-1.0 if job.controls.true_peak_limiter else -0.3,
        dynamic=True,
        audio_codec="pcm_s16le",
        sample_rate=44100,
        pre_filter=job.controls.manual_pre_filter(),
        extension="wav",
        progress=False,
        batch=len(job.input_paths) > 1,
    )

    for input_path, output_path in zip(job.input_paths, output_paths, strict=True):
        normalizer.add_media_file(input_path, output_path)

    normalizer.run_normalization()
    return output_paths


def run_reference_match(job: ReferenceMatchJob) -> list[str]:
    import matchering as mg

    ffmpeg_path = resolve_ffmpeg_path()
    os.environ["PATH"] = str(Path(ffmpeg_path).parent) + os.pathsep + os.environ.get("PATH", "")
    patch_silent_audio_subprocesses()
    Path(job.output_directory).mkdir(parents=True, exist_ok=True)
    output_paths = build_preview_output_paths(job.input_paths, job.output_directory)
    bit_depth_to_subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}

    if job.controls.bit_depth not in bit_depth_to_subtype:
        raise ValueError("Reference match bit depth must be 16, 24, or 32.")

    for input_path, output_path in zip(job.input_paths, output_paths, strict=True):
        LOGGER.info("Reference matching %s", input_path)
        mg.process(
            target=input_path,
            reference=job.reference_track_path,
            results=[
                mg.Result(
                    output_path,
                    bit_depth_to_subtype[job.controls.bit_depth],
                    use_limiter=job.controls.true_peak_limiter,
                    normalize=True,
                )
            ],
        )
        apply_reference_strength_blend(
            original_path=input_path,
            mastered_path=output_path,
            strength_percent=job.controls.reference_strength_percent,
        )

    return output_paths
