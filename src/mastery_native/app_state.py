from __future__ import annotations

from dataclasses import dataclass, field

from mastery_native.audio_files import dedupe_key, is_supported_audio_path, normalize_path

MAX_TRACKS = 10


@dataclass(slots=True)
class ImportResult:
    added: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    limit_reached: bool = False


@dataclass(slots=True)
class PreviewPair:
    original_path: str
    mastered_preview_path: str


@dataclass(slots=True)
class MasteringSessionState:
    track_paths: list[str] = field(default_factory=list)
    reference_track_path: str | None = None
    output_directory: str | None = None
    preview_pairs: list[PreviewPair] = field(default_factory=list)

    @property
    def has_preview_results(self) -> bool:
        return bool(self.preview_pairs)

    def clear_preview_outputs(self) -> None:
        self.preview_pairs.clear()

    def add_tracks(self, paths: list[str]) -> ImportResult:
        result = ImportResult()
        remaining_slots = max(0, MAX_TRACKS - len(self.track_paths))
        existing_keys = {dedupe_key(path) for path in self.track_paths}
        queued_keys: set[str] = set()

        for raw_path in paths:
            normalized = normalize_path(raw_path)
            key = dedupe_key(normalized)

            if not is_supported_audio_path(normalized):
                if normalized not in result.invalid:
                    result.invalid.append(normalized)
                continue

            if key in existing_keys or key in queued_keys:
                if normalized not in result.duplicates:
                    result.duplicates.append(normalized)
                continue

            if len(result.added) >= remaining_slots:
                result.limit_reached = True
                continue

            result.added.append(normalized)
            queued_keys.add(key)

        self.track_paths.extend(result.added)
        if result.added:
            self.clear_preview_outputs()
        return result

    def set_reference_track(self, raw_path: str) -> bool:
        normalized = normalize_path(raw_path)
        if not is_supported_audio_path(normalized):
            return False

        self.reference_track_path = normalized
        self.clear_preview_outputs()
        return True

    def register_preview_outputs(self, preview_paths: list[str]) -> None:
        if len(preview_paths) != len(self.track_paths):
            raise ValueError("Preview output count must match queued track count.")

        self.preview_pairs = [
            PreviewPair(original_path=original_path, mastered_preview_path=preview_path)
            for original_path, preview_path in zip(self.track_paths, preview_paths, strict=True)
        ]
