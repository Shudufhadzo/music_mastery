from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mastery_native.app_state import MAX_TRACKS, MasteringSessionState
from mastery_native.audio_files import AUDIO_FILE_DIALOG_FILTER, accepted_audio_paths
from mastery_native.engine import (
    ManualMasteringJob,
    MasteringControls,
    ReferenceMatchJob,
    run_manual_mastering,
    run_reference_match,
    save_mastered_previews,
    styled_controls,
)
from mastery_native.live_audio import (
    DEFAULT_CHANNELS,
    DEFAULT_SAMPLE_RATE,
    LiveAudioTrack,
    SwitchableAudioDevice,
    apply_live_mastering,
    build_waveform_peaks,
    decode_audio_file,
    load_live_audio_track,
    measure_audio_level_db,
    pcm16le_bytes,
)
from mastery_native.preset_store import MasteringPresetStore


def _format_decibels(value: float) -> str:
    return f"{int(value)} dB"


def _format_lufs(value: float) -> str:
    return f"{int(value)} LUFS"


CONTROL_TOOLTIPS = {
    "gain_db": "Higher plays the master louder.",
    "target_lufs": "Higher makes the finished song louder.",
    "clarity_percent": "Higher makes vocals and lead parts clearer.",
    "bass_percent": "Higher adds more bass and weight.",
    "treble_percent": "Higher adds more shine and air.",
    "punch_percent": "Higher makes drums hit harder.",
    "stereo_width_percent": "Higher makes the song feel wider.",
    "low_cut_hz": "Higher removes more low bass and rumble.",
    "high_cut_hz": "Lower softens the bright top end.",
    "true_peak_limiter": "On keeps loud peaks under control.",
    "auto_eq": "On gently balances the tone for you.",
    "reference_strength_percent": "Higher follows the reference song more closely.",
    "style_intensity": "Higher pushes the chosen preset harder.",
}

CONTROL_LABELS = {
    "gain_db": "Volume",
    "target_lufs": "Target Loudness",
    "clarity_percent": "Clarity",
    "bass_percent": "Bass",
    "treble_percent": "Treble",
    "punch_percent": "Punch",
    "stereo_width_percent": "Stereo Width",
    "low_cut_hz": "Low Cut",
    "high_cut_hz": "High Cut",
}


class AudioDropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(
        self,
        *,
        heading: str,
        detail: str,
        empty_state: str,
        button_text: str,
    ) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self._drag_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        self.heading_label = QLabel(heading)
        self.heading_label.setObjectName("dropZoneHeading")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("dropZoneDetail")
        self.icon_label = QLabel("^")
        self.icon_label.setObjectName("dropZoneIcon")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label = QLabel(empty_state)
        self.empty_state_label.setObjectName("dropZoneEmptyState")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.select_button = QPushButton(button_text)
        self.select_button.setObjectName("ghostButton")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if heading:
            layout.addWidget(self.heading_label)
        else:
            self.heading_label.hide()
        layout.addStretch(1)
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_state_label)
        if detail:
            layout.addWidget(self.detail_label)
        else:
            self.detail_label.hide()
        layout.addWidget(self.select_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

    def set_empty_state(self, message: str) -> None:
        self.empty_state_label.setText(message)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._extract_local_paths(event.mimeData()):
            self._drag_active = True
            self.update()
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self._drag_active = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self._drag_active = False
        self.update()
        paths = self._extract_local_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        border = QColor("#ff4b4b" if self._drag_active else "#2b2b2f")
        pen = QPen(border, 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 22, 22)

    @staticmethod
    def _extract_local_paths(mime_data) -> list[str]:
        if not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()]


class MasteringWorker(QThread):
    completed = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        *,
        reference_mode: bool,
        track_paths: list[str],
        preview_directory: str,
        controls: MasteringControls,
        reference_track_path: str | None,
    ) -> None:
        super().__init__()
        self.reference_mode = reference_mode
        self.track_paths = track_paths
        self.preview_directory = preview_directory
        self.controls = controls
        self.reference_track_path = reference_track_path

    def run(self) -> None:  # type: ignore[override]
        try:
            if self.reference_mode:
                if self.reference_track_path is None:
                    raise ValueError("Reference mode requires a reference track.")
                output_paths = run_reference_match(
                    ReferenceMatchJob(
                        input_paths=self.track_paths,
                        output_directory=self.preview_directory,
                        reference_track_path=self.reference_track_path,
                        controls=self.controls,
                    )
                )
            else:
                output_paths = run_manual_mastering(
                    ManualMasteringJob(
                        input_paths=self.track_paths,
                        output_directory=self.preview_directory,
                        controls=self.controls,
                    )
                )
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
            return

        self.completed.emit(output_paths)


class LiveMasteringWorker(QThread):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, *, original_audio, controls: MasteringControls, source_level_db: float) -> None:
        super().__init__()
        self.original_audio = original_audio
        self.controls = controls
        self.source_level_db = source_level_db

    def run(self) -> None:  # type: ignore[override]
        try:
            mastered_audio = apply_live_mastering(
                self.original_audio,
                self.controls,
                source_level_db=self.source_level_db,
            )
            waveform = build_waveform_peaks(mastered_audio)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
            return

        self.completed.emit(mastered_audio, waveform)


class WaveformView(QWidget):
    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks: list[float] = []
        self._accent = QColor(accent)
        self._active = False
        self._display_text = ""
        self._playhead_progress = 0.0
        self.setMinimumHeight(78)

    def set_peaks(self, peaks: list[float]) -> None:
        self._peaks = peaks
        self.update()

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def set_display_text(self, text: str) -> None:
        self._display_text = text
        self.update()

    def display_text(self) -> str:
        return self._display_text

    def set_playhead_progress(self, progress: float) -> None:
        self._playhead_progress = max(0.0, min(1.0, progress))
        self.update()

    def playhead_progress(self) -> float:
        return self._playhead_progress

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0f1114"))

        mid_y = self.height() / 2
        painter.setPen(QPen(QColor("#1b1e24"), 1))
        painter.drawLine(0, int(mid_y), self.width(), int(mid_y))

        if not self._peaks:
            painter.setPen(QPen(QColor("#22262d"), 2))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
            return

        bar_width = max(2, self.width() / max(1, len(self._peaks)))
        color = QColor(self._accent if self._active else QColor("#4d5562"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)

        for index, peak in enumerate(self._peaks):
            normalized = max(0.02, min(1.0, peak))
            height = normalized * (self.height() * 0.42)
            x = int(index * bar_width)
            width = max(1, int(bar_width - 1))
            top = int(mid_y - height)
            painter.drawRoundedRect(x, top, width, int(height * 2), 2, 2)

        outline = QColor(self._accent if self._active else QColor("#1f232a"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(outline, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)

        if self._display_text:
            painter.setPen(QColor("#f5f5f7"))
            font = painter.font()
            font.setPointSize(14)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                self.rect().adjusted(16, 0, -16, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._display_text,
            )

        playhead_x = int(self._playhead_progress * max(1, self.width() - 1))
        painter.setPen(QPen(QColor("#f5f5f7"), 2))
        painter.drawLine(playhead_x, 4, playhead_x, self.height() - 4)


class MasteryWindow(QMainWindow):
    def __init__(self, preset_store: MasteringPresetStore | None = None) -> None:
        super().__init__()
        self.audio_file_filter = AUDIO_FILE_DIALOG_FILTER
        self.session_state = MasteringSessionState()
        self.controls = MasteringControls()
        self.committed_controls = replace(self.controls)
        self.preset_store = preset_store or MasteringPresetStore()
        self.worker: MasteringWorker | None = None
        self.preview_root = Path(tempfile.mkdtemp(prefix="mastery-preview-"))

        self.control_value_labels: dict[str, QLabel] = {}
        self.control_text_labels: dict[str, QLabel] = {}
        self.control_sliders: dict[str, QSlider] = {}
        self.control_toggles: dict[str, QCheckBox] = {}
        self.control_formatters: dict[str, object] = {}
        self.control_info_buttons: dict[str, QPushButton] = {}
        self._applying_style = False
        self.live_track: LiveAudioTrack | None = None
        self.live_render_worker: LiveMasteringWorker | None = None
        self.pending_live_controls: MasteringControls | None = None
        self.active_source = "original"
        self.transport_state = "stopped"
        self.live_render_timer = QTimer(self)
        self.live_render_timer.setSingleShot(True)
        self.live_render_timer.timeout.connect(self._start_live_render)
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(40)
        self.position_timer.timeout.connect(self._update_transport_position)

        self.audio_device = SwitchableAudioDevice(self)
        audio_format = QAudioFormat()
        audio_format.setSampleRate(DEFAULT_SAMPLE_RATE)
        audio_format.setChannelCount(DEFAULT_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        output_device = QMediaDevices.defaultAudioOutput()
        if output_device.isFormatSupported(audio_format):
            self.audio_format = audio_format
        else:
            self.audio_format = output_device.preferredFormat()
        self.audio_sink = QAudioSink(output_device, self.audio_format, self)
        self.audio_sink.setBufferFrameCount(2048)
        self.audio_sink.setVolume(0.9)
        self.audio_sink.stateChanged.connect(self._on_audio_state_changed)

        self.reference_mode_button = QPushButton("Reference Match")
        self.reference_mode_button.setCheckable(True)
        self.reference_mode_button.hide()
        self.manual_mode_button = QPushButton("Manual Controls")
        self.manual_mode_button.setCheckable(True)
        self.manual_mode_button.hide()

        self.setWindowTitle("Music Mastery")
        self.resize(1420, 920)
        self.setMinimumSize(1220, 820)

        central = QWidget()
        central.setObjectName("appRoot")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(24, 18, 24, 22)
        root_layout.setSpacing(18)
        root_layout.addWidget(self._build_header())

        self.content_stack = QStackedWidget()
        self.home_page = self._build_home_page()
        self.workspace_page = self._build_workspace_page()
        self.content_stack.addWidget(self.home_page)
        self.content_stack.addWidget(self.workspace_page)
        root_layout.addWidget(self.content_stack, stretch=1)

        self.setCentralWidget(central)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._configure_keyboard_access()
        self._configure_tab_order()
        self._apply_styles()
        self._sync_mode_ui(reference_mode=True, force=True, show_workspace=False)
        self._refresh_reference()
        self._refresh_memory_combo()
        self._refresh_track_ui()
        self._set_status("")
        self._show_home_page()
        self._update_responsive_layouts()

    def _configure_keyboard_access(self) -> None:
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.escape_shortcut.activated.connect(self._handle_escape_shortcut)

        self.space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.space_shortcut.activated.connect(self._handle_space_shortcut)

        self._keyboard_activation_buttons = [
            self.back_button,
            self.home_reference_button,
            self.home_manual_button,
            self.original_upload_button,
            self.reference_zone.select_button,
            self.reference_track_zone.select_button,
            self.reference_apply_button,
            *self.quick_preset_buttons.values(),
            self.save_memory_button,
            self.undo_button,
            self.original_listen_button,
            self.mastered_listen_button,
            self.transport_play_button,
            self.transport_stop_button,
            self.revert_button,
            self.download_button,
        ]
        for button in self._keyboard_activation_buttons:
            button.installEventFilter(self)

    def _configure_tab_order(self) -> None:
        self.setTabOrder(self.home_reference_button, self.home_manual_button)
        self.setTabOrder(self.back_button, self.original_upload_button)
        self.setTabOrder(self.original_upload_button, self.quick_preset_buttons["Warm"])
        self.setTabOrder(self.quick_preset_buttons["Warm"], self.save_memory_button)
        self.setTabOrder(self.save_memory_button, self.undo_button)
        self.setTabOrder(self.undo_button, self.original_listen_button)
        self.setTabOrder(self.original_listen_button, self.mastered_listen_button)
        self.setTabOrder(self.mastered_listen_button, self.transport_play_button)
        self.setTabOrder(self.transport_play_button, self.transport_stop_button)
        self.setTabOrder(self.transport_stop_button, self.revert_button)
        self.setTabOrder(self.revert_button, self.download_button)
        self.setTabOrder(self.reference_zone.select_button, self.reference_track_zone.select_button)
        self.setTabOrder(self.reference_track_zone.select_button, self.reference_strength_slider)
        self.setTabOrder(self.reference_strength_slider, self.reference_apply_button)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.back_button = QPushButton("<")
        self.back_button.setObjectName("backButton")
        self.back_button.clicked.connect(self._show_home_page)
        self.back_button.hide()
        layout.addWidget(self.back_button)

        brand_badge = QLabel("M")
        brand_badge.setObjectName("brandBadge")
        self.brand_name_label = QLabel("Music Mastery")
        self.brand_name_label.setObjectName("brandName")
        layout.addWidget(brand_badge)
        layout.addWidget(self.brand_name_label)
        layout.addStretch(1)
        return header

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 18)
        layout.setSpacing(24)
        layout.addStretch(1)

        self.home_title_label = QLabel("Professional mastering made simple")
        self.home_title_label.setObjectName("heroTitle")
        self.home_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_subtitle_label = QLabel("Choose how you want to master your track.")
        self.home_subtitle_label.setObjectName("heroSubtitle")
        self.home_subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.home_title_label)
        layout.addWidget(self.home_subtitle_label)

        card_row = QHBoxLayout()
        card_row.setSpacing(22)
        self.home_reference_button = self._build_mode_card(
            "Match a Reference",
            "Upload a polished song and match your track to its sound.",
            "R",
            lambda: self._sync_mode_ui(reference_mode=True),
        )
        self.home_manual_button = self._build_mode_card(
            "Manual Controls",
            "Shape your track with simple live sliders and compare instantly.",
            "M",
            lambda: self._sync_mode_ui(reference_mode=False),
        )
        card_row.addStretch(1)
        card_row.addWidget(self.home_reference_button)
        card_row.addWidget(self.home_manual_button)
        card_row.addStretch(1)
        layout.addLayout(card_row)

        footer = QLabel("Reference matching is great for beginners.")
        footer.setObjectName("homeFooter")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer)
        layout.addStretch(1)
        return page

    def _build_mode_card(self, title: str, detail: str, icon_text: str, callback) -> QPushButton:
        button = QPushButton(title)
        button.setObjectName("modeCard")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        layout = QVBoxLayout(button)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)
        icon = QLabel(icon_text)
        icon.setObjectName("modeCardIcon")
        heading = QLabel(title)
        heading.setObjectName("modeCardTitle")
        detail_label = QLabel(detail)
        detail_label.setObjectName("modeCardDetail")
        detail_label.setWordWrap(True)
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(heading)
        layout.addWidget(detail_label)
        layout.addStretch(1)
        button.setMinimumSize(360, 246)
        return button

    def _build_workspace_page(self) -> QWidget:
        page = QWidget()
        self.workspace_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, page)
        self.workspace_layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_layout.setSpacing(24)
        self.main_panel = self._build_left_panel()
        self.main_panel.setObjectName("workspaceCanvas")
        self.main_panel.setAutoFillBackground(False)
        self.main_panel_scroll = QScrollArea()
        self.main_panel_scroll.setObjectName("workspaceScroll")
        self.main_panel_scroll.setWidgetResizable(True)
        self.main_panel_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.main_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.main_panel_scroll.viewport().setObjectName("workspaceViewport")
        self.main_panel_scroll.viewport().setAutoFillBackground(False)
        self.main_panel_scroll.setWidget(self.main_panel)
        self.sidebar = self._build_sidebar()
        self.workspace_layout.addWidget(self.main_panel_scroll, 7)
        self.workspace_layout.addWidget(self.sidebar, 3)
        return page

    def _build_stepper(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("stepperFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addStretch(1)

        self.step_items: list[QWidget] = []
        self.step_circles: list[QLabel] = []
        self.step_labels: list[QLabel] = []
        for index in range(3):
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(8)
            item_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            circle = QLabel(str(index + 1))
            circle.setObjectName("stepCircle")
            circle.setProperty("stepState", "idle")
            circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label = QLabel("")
            label.setObjectName("stepLabel")
            label.setProperty("stepState", "idle")
            item_layout.addWidget(circle, alignment=Qt.AlignmentFlag.AlignCenter)
            item_layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
            self.step_items.append(item)
            self.step_circles.append(circle)
            self.step_labels.append(label)
            layout.addWidget(item)
            if index < 2:
                connector = QFrame()
                connector.setObjectName("stepConnector")
                connector.setFixedHeight(2)
                connector.setFixedWidth(56)
                layout.addWidget(connector)
        layout.addStretch(1)
        return frame

    def _build_stage_heading(self, number: str, title: str, detail: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        badge = QLabel(number)
        badge.setObjectName("sectionBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        detail_label = QLabel(detail)
        detail_label.setObjectName("sectionDetail")
        text_column.addWidget(title_label)
        if detail:
            text_column.addWidget(detail_label)
        else:
            detail_label.hide()
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_column)
        layout.addStretch(1)
        container.title_label = title_label
        container.detail_label = detail_label
        return container

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        layout.addWidget(self._build_stepper())

        self.manual_top_section = QWidget()
        manual_top_layout = QVBoxLayout(self.manual_top_section)
        manual_top_layout.setContentsMargins(0, 0, 0, 0)
        manual_top_layout.setSpacing(14)
        manual_heading = self._build_stage_heading("1", "Your Track", "")
        self.manual_section_detail = manual_heading.detail_label
        manual_top_layout.addWidget(manual_heading)
        self.manual_track_zone = AudioDropZone(
            heading="",
            detail="",
            empty_state="Drop your track here",
            button_text="Upload Track",
        )
        self.manual_track_zone.files_dropped.connect(self.import_tracks)
        self.manual_track_zone.select_button.clicked.connect(self.pick_tracks)
        self.original_upload_button = self.manual_track_zone.select_button
        manual_top_layout.addWidget(self.manual_track_zone)
        layout.addWidget(self.manual_top_section)

        self.reference_top_section = QWidget()
        reference_top_layout = QGridLayout(self.reference_top_section)
        reference_top_layout.setContentsMargins(0, 0, 0, 0)
        reference_top_layout.setHorizontalSpacing(18)
        reference_top_layout.setVerticalSpacing(14)

        reference_card = QFrame()
        reference_card.setObjectName("uploadGroup")
        reference_card_layout = QVBoxLayout(reference_card)
        reference_card_layout.setContentsMargins(22, 22, 22, 22)
        reference_card_layout.setSpacing(12)
        left_heading = self._build_stage_heading("1", "Reference Track", "")
        self.reference_section_detail_left = left_heading.detail_label
        reference_card_layout.addWidget(left_heading)
        self.reference_zone = AudioDropZone(
            heading="",
            detail="",
            empty_state="Drop your reference track",
            button_text="Upload Reference",
        )
        self.reference_zone.files_dropped.connect(self.import_reference_tracks)
        self.reference_zone.select_button.clicked.connect(self.pick_reference_track)
        reference_card_layout.addWidget(self.reference_zone)

        target_card = QFrame()
        target_card.setObjectName("uploadGroup")
        target_card_layout = QVBoxLayout(target_card)
        target_card_layout.setContentsMargins(22, 22, 22, 22)
        target_card_layout.setSpacing(12)
        right_heading = self._build_stage_heading("2", "Your Track", "")
        self.reference_section_detail_right = right_heading.detail_label
        target_card_layout.addWidget(right_heading)
        self.reference_track_zone = AudioDropZone(
            heading="",
            detail="",
            empty_state="Drop your track to master",
            button_text="Upload Track",
        )
        self.reference_track_zone.files_dropped.connect(self.import_tracks)
        self.reference_track_zone.select_button.clicked.connect(self.pick_tracks)
        target_card_layout.addWidget(self.reference_track_zone)

        reference_top_layout.addWidget(reference_card, 0, 0)
        reference_top_layout.addWidget(target_card, 0, 1)
        layout.addWidget(self.reference_top_section)

        self.reference_toolbar = QFrame()
        self.reference_toolbar.setObjectName("inlineToolbar")
        self.reference_controls_container = self.reference_toolbar
        reference_toolbar_layout = QHBoxLayout(self.reference_toolbar)
        reference_toolbar_layout.setContentsMargins(18, 16, 18, 16)
        reference_toolbar_layout.setSpacing(14)
        reference_toolbar_layout.addWidget(QLabel("Reference Strength"))
        self.reference_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.reference_strength_slider.setRange(0, 100)
        self.reference_strength_slider.setValue(self.controls.reference_strength_percent)
        self.reference_strength_slider.setObjectName("masterSlider")
        self.reference_strength_slider.valueChanged.connect(self._handle_reference_strength_change)
        self.reference_strength_value_label = QLabel("100%")
        self.reference_strength_value_label.setObjectName("controlValue")
        self.reference_apply_button = QPushButton("Apply")
        self.reference_apply_button.setObjectName("accentButton")
        self.reference_apply_button.clicked.connect(self.start_mastering)
        self.apply_changes_button = self.reference_apply_button
        reference_toolbar_layout.addWidget(self.reference_strength_slider, stretch=1)
        reference_toolbar_layout.addWidget(self.reference_strength_value_label)
        reference_toolbar_layout.addWidget(self.reference_apply_button)
        layout.addWidget(self.reference_toolbar)

        self.compare_panel = QFrame()
        self.compare_panel.setObjectName("comparePanel")
        compare_layout = QVBoxLayout(self.compare_panel)
        compare_layout.setContentsMargins(24, 22, 24, 22)
        compare_layout.setSpacing(14)

        compare_header = QHBoxLayout()
        compare_header.setContentsMargins(0, 0, 0, 0)
        compare_header.setSpacing(12)
        self.compare_heading_label = QLabel("Compare")
        self.compare_heading_label.setObjectName("compareHeading")
        self.track_name_chip = QLabel("")
        self.track_name_chip.setObjectName("trackChip")
        self.track_selector = QComboBox()
        self.track_selector.setObjectName("memoryCombo")
        self.track_selector.currentIndexChanged.connect(self._on_selected_track_changed)
        self.track_selector.hide()
        compare_header.addWidget(self.compare_heading_label)
        compare_header.addWidget(self.track_name_chip)
        compare_header.addWidget(self.track_selector, stretch=1)
        compare_layout.addLayout(compare_header)
        self.compare_heading_label.hide()

        self.original_card = QFrame()
        self.original_card.setObjectName("trackCard")
        original_layout = QVBoxLayout(self.original_card)
        original_layout.setContentsMargins(20, 18, 20, 18)
        original_layout.setSpacing(12)
        self.original_file_label = QLabel("")
        self.original_file_label.setObjectName("trackCardFile")
        self.original_file_label.hide()
        self.original_title_label = QLabel("Original")
        self.original_title_label.setObjectName("trackCardTitle")
        self.original_waveform = WaveformView("#78b8ff")
        original_actions = QHBoxLayout()
        original_actions.setSpacing(10)
        self.original_listen_button = QPushButton("A")
        self.original_listen_button.setCheckable(True)
        self.original_listen_button.setObjectName("sourceButton")
        self.original_listen_button.clicked.connect(lambda: self._set_active_source("original"))
        original_actions.addWidget(self.original_title_label)
        original_actions.addWidget(self.original_file_label)
        original_actions.addStretch(1)
        original_actions.addWidget(self.original_listen_button)
        original_layout.addLayout(original_actions)
        original_layout.addWidget(self.original_waveform)
        compare_layout.addWidget(self.original_card)

        self.mastered_card = QFrame()
        self.mastered_card.setObjectName("trackCard")
        mastered_layout = QVBoxLayout(self.mastered_card)
        mastered_layout.setContentsMargins(20, 18, 20, 18)
        mastered_layout.setSpacing(12)
        self.mastered_file_label = QLabel("")
        self.mastered_file_label.setObjectName("trackCardFile")
        self.mastered_file_label.hide()
        self.mastered_title_label = QLabel("Mastered")
        self.mastered_title_label.setObjectName("trackCardTitle")
        self.mastered_waveform = WaveformView("#ff7b1a")
        mastered_actions = QHBoxLayout()
        mastered_actions.setSpacing(10)
        self.mastered_listen_button = QPushButton("B")
        self.mastered_listen_button.setCheckable(True)
        self.mastered_listen_button.setObjectName("sourceButton")
        self.mastered_listen_button.clicked.connect(lambda: self._set_active_source("mastered"))
        mastered_actions.addWidget(self.mastered_title_label)
        mastered_actions.addWidget(self.mastered_file_label)
        mastered_actions.addStretch(1)
        mastered_actions.addWidget(self.mastered_listen_button)
        mastered_layout.addLayout(mastered_actions)
        mastered_layout.addWidget(self.mastered_waveform)
        compare_layout.addWidget(self.mastered_card)

        self.listen_group = QButtonGroup(self)
        self.listen_group.setExclusive(True)
        self.listen_group.addButton(self.original_listen_button)
        self.listen_group.addButton(self.mastered_listen_button)
        self.original_listen_button.setChecked(True)

        self.transport_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.transport_layout.setSpacing(12)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setObjectName("masterSlider")
        self.position_slider.setRange(0, 1000)
        self.position_slider.setValue(0)
        self.position_slider.valueChanged.connect(self._seek_from_slider)
        self.transport_play_button = QPushButton("Play")
        self.transport_play_button.setObjectName("ghostButton")
        self.transport_play_button.clicked.connect(self.toggle_transport_playback)
        self.transport_stop_button = QPushButton("Stop")
        self.transport_stop_button.setObjectName("ghostButton")
        self.transport_stop_button.clicked.connect(self.stop_transport)
        self.revert_button = QPushButton("Reset")
        self.revert_button.setObjectName("ghostButton")
        self.revert_button.setVisible(True)
        self.revert_button.clicked.connect(self.undo_control_changes)
        self.download_button = QPushButton("Export")
        self.download_button.setObjectName("accentButton")
        self.download_button.setVisible(True)
        self.download_button.clicked.connect(self.save_mastered_tracks)
        self.transport_layout.addWidget(self.position_slider, stretch=1)
        self.transport_layout.addWidget(self.transport_play_button)
        self.transport_layout.addWidget(self.transport_stop_button)
        self.transport_layout.addWidget(self.revert_button)
        self.transport_layout.addWidget(self.download_button)
        compare_layout.addLayout(self.transport_layout)
        layout.addWidget(self.compare_panel, stretch=1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        return panel

    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("sidebar")
        panel.setAutoFillBackground(False)
        panel.setMinimumWidth(430)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.sidebar_heading = QLabel("Mastering")
        self.sidebar_heading.setObjectName("sidebarHeading")
        layout.addWidget(self.sidebar_heading)
        self.manual_controls_container = QWidget()
        self.manual_controls_container.setObjectName("manualControlsCanvas")
        self.manual_controls_container.setAutoFillBackground(False)
        manual_controls_layout = QVBoxLayout(self.manual_controls_container)
        manual_controls_layout.setContentsMargins(0, 0, 0, 0)
        manual_controls_layout.setSpacing(16)

        preset_label = QLabel("Quick Presets")
        preset_label.setObjectName("miniLabel")
        manual_controls_layout.addWidget(preset_label)

        preset_row = QGridLayout()
        preset_row.setHorizontalSpacing(8)
        preset_row.setVerticalSpacing(8)
        self.style_combo = QComboBox()
        self.style_combo.setObjectName("memoryCombo")
        self.style_combo.addItems(["Custom", "Clean", "Warm", "Punch", "Wide", "Vocal", "Bright"])
        self.style_combo.currentTextChanged.connect(self._on_style_changed)
        self.style_combo.hide()
        self.quick_preset_buttons: dict[str, QPushButton] = {}
        for index, (label_text, style_name) in enumerate([
            ("Warm", "Warm"),
            ("Punchy", "Punch"),
            ("Balanced", "Clean"),
            ("Bright", "Bright"),
        ]):
            button = QPushButton(label_text)
            button.setCheckable(True)
            button.setObjectName("presetChip")
            button.clicked.connect(lambda _checked=False, name=style_name: self._set_quick_style(name))
            self.quick_preset_buttons[style_name] = button
            preset_row.addWidget(button, index // 2, index % 2)
        manual_controls_layout.addLayout(preset_row)
        manual_controls_layout.addWidget(self.style_combo)

        intensity_container = QWidget()
        intensity_layout = QVBoxLayout(intensity_container)
        intensity_layout.setContentsMargins(0, 0, 0, 0)
        intensity_layout.setSpacing(8)
        intensity_header = QHBoxLayout()
        intensity_header.setContentsMargins(0, 0, 0, 0)
        intensity_label = QLabel("Preset Strength")
        intensity_label.setObjectName("controlLabel")
        intensity_info = self._build_info_button("style_intensity")
        self.style_intensity_value_label = QLabel("60%")
        self.style_intensity_value_label.setObjectName("controlValue")
        intensity_header.addWidget(intensity_label)
        intensity_header.addWidget(intensity_info)
        intensity_header.addStretch(1)
        intensity_header.addWidget(self.style_intensity_value_label)
        self.style_intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.style_intensity_slider.setRange(0, 100)
        self.style_intensity_slider.setValue(60)
        self.style_intensity_slider.setObjectName("masterSlider")
        self.style_intensity_slider.setEnabled(False)
        self.style_intensity_slider.valueChanged.connect(self._on_style_intensity_changed)
        intensity_layout.addLayout(intensity_header)
        intensity_layout.addWidget(self.style_intensity_slider)
        manual_controls_layout.addWidget(intensity_container)

        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["gain_db"],
            attribute="gain_db",
            minimum=-12,
            maximum=12,
            formatter=_format_decibels,
            converter=float,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["target_lufs"],
            attribute="target_lufs",
            minimum=-24,
            maximum=0,
            formatter=_format_lufs,
            converter=float,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["clarity_percent"],
            attribute="clarity_percent",
            minimum=0,
            maximum=100,
            formatter=lambda value: f"{int(value)}%",
            converter=int,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["bass_percent"],
            attribute="bass_percent",
            minimum=0,
            maximum=100,
            formatter=lambda value: f"{int(value)}%",
            converter=int,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["treble_percent"],
            attribute="treble_percent",
            minimum=0,
            maximum=100,
            formatter=lambda value: f"{int(value)}%",
            converter=int,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["punch_percent"],
            attribute="punch_percent",
            minimum=0,
            maximum=100,
            formatter=lambda value: f"{int(value)}%",
            converter=int,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["stereo_width_percent"],
            attribute="stereo_width_percent",
            minimum=0,
            maximum=100,
            formatter=lambda value: f"{int(value)}%",
            converter=int,
        )
        cut_row = QHBoxLayout()
        cut_row.setSpacing(12)
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["low_cut_hz"],
            attribute="low_cut_hz",
            minimum=20,
            maximum=80,
            formatter=lambda value: f"{int(value)} Hz",
            converter=int,
        )
        self._add_slider_control(
            manual_controls_layout,
            label_text=CONTROL_LABELS["high_cut_hz"],
            attribute="high_cut_hz",
            minimum=6000,
            maximum=20000,
            formatter=lambda value: f"{int(value)} Hz",
            converter=int,
        )

        self.true_peak_checkbox = self._build_toggle("Peak Safety", "true_peak_limiter")
        self.auto_eq_checkbox = self._build_toggle("Tone Fix", "auto_eq")
        manual_controls_layout.addWidget(self.true_peak_checkbox)
        manual_controls_layout.addWidget(self.auto_eq_checkbox)

        memory_label = QLabel("Saved Settings")
        memory_label.setObjectName("miniLabel")
        manual_controls_layout.addWidget(memory_label)
        memory_row = QHBoxLayout()
        memory_row.setSpacing(10)
        self.memory_combo = QComboBox()
        self.memory_combo.setObjectName("memoryCombo")
        self.memory_combo.currentTextChanged.connect(self._on_memory_selected)
        self.save_memory_button = QPushButton("Save")
        self.save_memory_button.setObjectName("ghostButton")
        self.save_memory_button.clicked.connect(self.save_current_memory)
        memory_row.addWidget(self.memory_combo, stretch=1)
        memory_row.addWidget(self.save_memory_button)
        manual_controls_layout.addLayout(memory_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setObjectName("ghostButton")
        self.undo_button.clicked.connect(self.undo_control_changes)
        action_row.addStretch(1)
        action_row.addWidget(self.undo_button)
        manual_controls_layout.addLayout(action_row)

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.viewport().setObjectName("sidebarViewport")
        self.sidebar_scroll.viewport().setAutoFillBackground(False)
        self.sidebar_scroll.setWidget(self.manual_controls_container)
        # setWidget can force a light auto-fill on the child widget; restore it.
        self.manual_controls_container.setAutoFillBackground(False)
        self.sidebar_scroll.viewport().setAutoFillBackground(False)
        layout.addWidget(self.sidebar_scroll)

        return panel

    def _add_slider_control(
        self,
        layout: QVBoxLayout,
        *,
        label_text: str,
        attribute: str,
        minimum: int,
        maximum: int,
        formatter,
        converter,
    ) -> None:
        container = QWidget()
        row_layout = QVBoxLayout(container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        label = QLabel(label_text)
        label.setObjectName("controlLabel")
        self.control_text_labels[attribute] = label
        info_button = self._build_info_button(attribute)
        value_label = QLabel(formatter(getattr(self.controls, attribute)))
        value_label.setObjectName("controlValue")
        header.addWidget(label)
        header.addWidget(info_button)
        header.addStretch(1)
        header.addWidget(value_label)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(getattr(self.controls, attribute)))
        slider.setObjectName("masterSlider")
        slider.valueChanged.connect(
            lambda current_value, attr=attribute, fmt=formatter, conv=converter: self._handle_slider_change(
                attr,
                current_value,
                fmt,
                conv,
            )
        )

        self.control_value_labels[attribute] = value_label
        self.control_sliders[attribute] = slider
        self.control_formatters[attribute] = formatter

        row_layout.addLayout(header)
        row_layout.addWidget(slider)
        layout.addWidget(container)

    def _build_info_button(self, attribute: str) -> QPushButton:
        info_button = QPushButton("i")
        info_button.setObjectName("infoButton")
        info_button.setToolTip(CONTROL_TOOLTIPS[attribute])
        info_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.control_info_buttons[attribute] = info_button
        return info_button

    def _build_toggle(self, label_text: str, attribute: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toggle = QCheckBox(label_text)
        toggle.setObjectName("toggle")
        toggle.setToolTip(CONTROL_TOOLTIPS[attribute])
        toggle.setChecked(bool(getattr(self.controls, attribute)))
        toggle.toggled.connect(lambda checked, attr=attribute: self._update_control(attr, checked))
        self.control_toggles[attribute] = toggle
        layout.addWidget(toggle)
        layout.addWidget(self._build_info_button(attribute))
        layout.addStretch(1)
        return container

    def _handle_slider_change(self, attribute: str, raw_value: int, formatter, converter) -> None:
        value = converter(raw_value)
        self.control_value_labels[attribute].setText(formatter(value))
        self._update_control(attribute, value)

    def _handle_reference_strength_change(self, value: int) -> None:
        self.reference_strength_value_label.setText(f"{value}%")
        self._update_control("reference_strength_percent", int(value))

    def _on_style_changed(self, style_name: str) -> None:
        enabled = style_name != "Custom"
        self.style_intensity_slider.setEnabled(enabled)
        self._sync_quick_preset_buttons(style_name)
        if not enabled:
            return
        self._apply_style_selection()

    def _set_quick_style(self, style_name: str) -> None:
        was_blocked = self.style_combo.blockSignals(True)
        self.style_combo.setCurrentText(style_name)
        self.style_combo.blockSignals(was_blocked)
        self.style_intensity_slider.setEnabled(style_name != "Custom")
        self._sync_quick_preset_buttons(style_name)
        if style_name != "Custom":
            self._apply_style_selection()

    def _sync_quick_preset_buttons(self, style_name: str) -> None:
        for preset_name, button in self.quick_preset_buttons.items():
            blocked = button.blockSignals(True)
            button.setChecked(preset_name == style_name)
            button.blockSignals(blocked)

    def _on_style_intensity_changed(self, value: int) -> None:
        self.style_intensity_value_label.setText(f"{value}%")
        if self.style_combo.currentText() == "Custom":
            return
        self._apply_style_selection()

    def _apply_style_selection(self) -> None:
        style_name = self.style_combo.currentText()
        if style_name == "Custom":
            return

        styled = styled_controls(style_name, self.style_intensity_slider.value())
        styled.gain_db = self.controls.gain_db
        styled.target_lufs = self.controls.target_lufs
        styled.reference_strength_percent = self.controls.reference_strength_percent
        self._applying_style = True
        try:
            self._apply_controls(
                styled,
                announce=False,
            )
        finally:
            self._applying_style = False

    def _apply_controls(self, controls: MasteringControls, *, announce: bool = True) -> None:
        previous_controls = replace(self.controls)
        self.controls = replace(controls)
        self._sync_control_widgets()

        if previous_controls == self.controls:
            return

        if not self.reference_mode_button.isChecked():
            self._schedule_live_render()
            if announce:
                self._set_status("")
        elif self.session_state.has_preview_results:
            self.revert_preview(status="Apply changes")
        elif announce:
            self._set_status("")

    def _sync_control_widgets(self) -> None:
        strength_blocked = self.reference_strength_slider.blockSignals(True)
        self.reference_strength_slider.setValue(int(self.controls.reference_strength_percent))
        self.reference_strength_slider.blockSignals(strength_blocked)
        self.reference_strength_value_label.setText(f"{int(self.controls.reference_strength_percent)}%")

        for attribute, slider in self.control_sliders.items():
            value = int(getattr(self.controls, attribute))
            was_blocked = slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(was_blocked)
            formatter = self.control_formatters[attribute]
            self.control_value_labels[attribute].setText(formatter(getattr(self.controls, attribute)))

        for attribute, toggle in self.control_toggles.items():
            was_blocked = toggle.blockSignals(True)
            toggle.setChecked(bool(getattr(self.controls, attribute)))
            toggle.blockSignals(was_blocked)
        self._sync_quick_preset_buttons(self.style_combo.currentText())

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                color: #f6f4f1;
                font-family: "Segoe UI Variable Text", "Segoe UI";
                font-size: 15px;
            }
            QMainWindow, QWidget#appRoot {
                background: #050506;
            }
            QToolTip {
                background: #111214;
                color: #f6f4f1;
                border: 1px solid #232428;
                padding: 8px 10px;
            }
            #backButton {
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                border: none;
                border-radius: 18px;
                background: transparent;
                color: #d9dadf;
                font-size: 28px;
                font-weight: 600;
            }
            #backButton:hover {
                background: #121316;
            }
            #brandBadge {
                min-width: 44px;
                min-height: 44px;
                max-width: 44px;
                max-height: 44px;
                border-radius: 22px;
                background: #24110f;
                color: #ff5a36;
                font-size: 20px;
                font-weight: 700;
                qproperty-alignment: AlignCenter;
            }
            #brandName {
                font-size: 22px;
                font-weight: 700;
            }
            #heroTitle {
                font-size: 52px;
                font-weight: 800;
                color: #ffffff;
            }
            #heroSubtitle, #homeFooter {
                color: #8b8e97;
                font-size: 18px;
            }
            #modeCard {
                color: transparent;
                padding: 0;
                text-align: left;
                border: 1px solid #1c1d20;
                border-radius: 28px;
                background: #0c0d0f;
            }
            #modeCard:hover {
                border: 1px solid #3a1711;
                background: #101114;
            }
            #modeCardIcon {
                min-width: 56px;
                min-height: 56px;
                max-width: 56px;
                max-height: 56px;
                border-radius: 18px;
                background: #141518;
                color: #ff6a3a;
                font-size: 28px;
                font-weight: 700;
                qproperty-alignment: AlignCenter;
            }
            #modeCardTitle {
                font-size: 20px;
                font-weight: 700;
                color: #ffffff;
            }
            #modeCardDetail {
                color: #8d9098;
                font-size: 15px;
                line-height: 1.4;
            }
            #stepCircle {
                min-width: 44px;
                min-height: 44px;
                max-width: 44px;
                max-height: 44px;
                border-radius: 22px;
                border: 2px solid #202226;
                background: #09090a;
                color: #6e727a;
                font-weight: 700;
            }
            #stepCircle[stepState="active"], #stepCircle[stepState="done"] {
                border-color: #ff4b38;
                color: #ffffff;
            }
            #stepCircle[stepState="done"] {
                background: #ff4b38;
                color: #050506;
            }
            #stepLabel {
                color: #757983;
                font-size: 16px;
                font-weight: 600;
            }
            #stepLabel[stepState="active"], #stepLabel[stepState="done"] {
                color: #ffffff;
            }
            #stepConnector {
                background: #17181b;
                border-radius: 1px;
            }
            #sidebar, #comparePanel, #inlineToolbar, #uploadGroup, #trackCard, #trackChip, #memoryCombo, #dropZone {
                background: #0d0e10;
                border-radius: 26px;
                border: 1px solid #1c1d21;
            }
            #compareHeading, #sidebarHeading, #sectionTitle {
                font-size: 18px;
                font-weight: 700;
                color: #ffffff;
            }
            #miniLabel, #sectionDetail, #dropZoneDetail, #controlValue, #homeFooter, #trackCardFile {
                color: #8b8f98;
            }
            #sectionBadge {
                min-width: 38px;
                min-height: 38px;
                max-width: 38px;
                max-height: 38px;
                border-radius: 19px;
                background: #2b0f12;
                color: #ff5542;
                font-weight: 700;
            }
            #dropZone {
                background: #08090b;
                min-height: 220px;
            }
            #dropZoneIcon {
                min-width: 76px;
                min-height: 76px;
                max-width: 76px;
                max-height: 76px;
                border-radius: 22px;
                background: #131418;
                color: #7b7f88;
                font-size: 34px;
                font-weight: 700;
            }
            #dropZoneEmptyState, #trackChip {
                color: #ffffff;
                font-size: 18px;
                font-weight: 600;
            }
            #trackChip {
                min-height: 28px;
                padding: 0 0;
                border: none;
                background: transparent;
                color: #ffffff;
                font-size: 18px;
                font-weight: 700;
            }
            #trackCard {
                background: #111216;
            }
            #trackCardTitle {
                color: #ffffff;
                font-size: 17px;
                font-weight: 700;
            }
            #ghostButton {
                min-height: 42px;
                padding: 0 18px;
                border-radius: 16px;
                border: 1px solid #292b31;
                background: #121317;
                color: #ffffff;
                font-weight: 600;
            }
            #ghostButton:hover {
                border: 1px solid #ff5a36;
            }
            #ghostButton:checked {
                border: 1px solid #ff5a36;
                background: #28120f;
                color: #ffffff;
            }
            #sourceButton {
                min-width: 44px;
                min-height: 36px;
                max-width: 44px;
                max-height: 36px;
                border-radius: 14px;
                border: 1px solid #2a2c31;
                background: #121317;
                color: #9aa0aa;
                font-weight: 700;
            }
            #sourceButton:checked {
                border-color: #ff5a36;
                background: #ff5a36;
                color: #050506;
            }
            #presetChip {
                min-height: 34px;
                padding: 0 14px;
                border-radius: 16px;
                border: 1px solid #26282d;
                background: #141519;
                color: #ffffff;
                font-weight: 600;
            }
            #presetChip:checked {
                background: #ff5a36;
                border-color: #ff5a36;
                color: #050506;
            }
            #infoButton {
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
                padding: 0;
                border-radius: 10px;
                border: 1px solid #2c2f35;
                background: #14161a;
                color: #cfd1d5;
                font-size: 12px;
                font-weight: 700;
            }
            #infoButton:hover {
                border: 1px solid #ff5a36;
                color: #ffffff;
            }
            #accentButton {
                min-height: 44px;
                padding: 0 22px;
                border: none;
                border-radius: 16px;
                background: #ff5a36;
                color: #060607;
                font-weight: 700;
            }
            #accentButton:disabled {
                background: #4a1e22;
                color: #a38a8d;
            }
            #statusLabel {
                min-height: 28px;
                color: #aeb2bb;
            }
            #controlLabel {
                font-size: 15px;
                font-weight: 600;
            }
            #memoryCombo {
                min-height: 42px;
                padding: 0 10px;
                border: 1px solid #2c2f35;
                color: #ffffff;
            }
            #workspaceScroll {
                background: transparent;
                border: none;
            }
            #workspaceCanvas, #workspaceViewport {
                background: transparent;
                border: none;
            }
            #sidebarScroll, #sidebarViewport, #manualControlsCanvas {
                background: #0d0e10;
                border: none;
            }
            #manualControlsCanvas {
                border-radius: 0;
            }
            QScrollBar:vertical {
                width: 8px;
                margin: 2px;
                background: transparent;
            }
            QScrollBar::handle:vertical {
                background: #2a2d33;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3b4049;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                width: 0px;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
            #masterSlider::groove:horizontal {
                background: #1a1c20;
                height: 6px;
                border-radius: 3px;
            }
            #masterSlider::handle:horizontal {
                background: #ff5a36;
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
            }
            #toggle {
                spacing: 10px;
                font-size: 15px;
                font-weight: 600;
            }
            #toggle::indicator {
                width: 42px;
                height: 24px;
                border-radius: 12px;
                background: #1d2025;
            }
            #toggle::indicator:checked {
                background: #ff5a36;
            }
            """
        )

    def _show_home_page(self) -> None:
        self.content_stack.setCurrentWidget(self.home_page)
        self.back_button.hide()
        self.sidebar.hide()

    def _update_responsive_layouts(self) -> None:
        width = self.width()
        height = self.height()
        is_narrow_workspace = width < 1220
        self.workspace_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if is_narrow_workspace else QBoxLayout.Direction.LeftToRight
        )
        self.workspace_layout.setSpacing(16 if width < 1500 else 24)
        self.transport_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if width < 1420 else QBoxLayout.Direction.LeftToRight
        )

        if is_narrow_workspace:
            self.sidebar.setMinimumWidth(0)
            self.sidebar.setMaximumWidth(16777215)
            self.sidebar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            if width >= 1760:
                sidebar_width = 430
            elif width >= 1540:
                sidebar_width = 400
            elif height < 860:
                sidebar_width = 350
            else:
                sidebar_width = 370
            self.sidebar.setMinimumWidth(sidebar_width)
            self.sidebar.setMaximumWidth(sidebar_width)
            self.sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_responsive_layouts()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if (
            watched in getattr(self, "_keyboard_activation_buttons", [])
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            if watched.isEnabled() and watched.isVisible():
                watched.click()
                return True
        return super().eventFilter(watched, event)

    def _handle_escape_shortcut(self) -> None:
        if self.content_stack.currentWidget() is not self.workspace_page:
            return
        self.stop_transport()
        self._show_home_page()

    def _handle_space_shortcut(self) -> None:
        if self.content_stack.currentWidget() is not self.workspace_page:
            return
        focused_widget = self.focusWidget()
        if isinstance(focused_widget, (QComboBox, QSlider)):
            return
        if self.transport_play_button.isEnabled():
            self.toggle_transport_playback()

    def _update_stepper_state(self) -> None:
        reference_mode = self.reference_mode_button.isChecked()
        if reference_mode:
            labels = ["Reference", "Your Track", "Compare"]
            completed = 0
            active = 0
            if self.session_state.reference_track_path:
                completed = 1
                active = 1
            if self.session_state.track_paths:
                completed = 2
                active = 2 if self.session_state.has_preview_results else 1
            if self.session_state.has_preview_results:
                completed = 3
                active = 2
        else:
            labels = ["Upload", "Adjust", "Compare"]
            if not self.session_state.track_paths:
                completed = 0
                active = 0
            else:
                completed = 1
                active = 2 if self.live_track is not None else 1

        for label, text in zip(self.step_labels, labels, strict=True):
            label.setText(text)

        for index, (circle, label) in enumerate(zip(self.step_circles, self.step_labels, strict=True)):
            state = "done" if index < completed else "active" if index == active else "idle"
            circle.setProperty("stepState", state)
            label.setProperty("stepState", state)
            circle.style().unpolish(circle)
            circle.style().polish(circle)
            label.style().unpolish(label)
            label.style().polish(label)
            circle.update()
            label.update()

    def _sync_mode_ui(self, *, reference_mode: bool, force: bool = False, show_workspace: bool = True) -> None:
        previous_mode = self.reference_mode_button.isChecked()
        self.reference_mode_button.setChecked(reference_mode)
        self.manual_mode_button.setChecked(not reference_mode)
        self.reference_top_section.setVisible(reference_mode)
        self.reference_toolbar.setVisible(reference_mode)
        self.manual_top_section.setVisible(not reference_mode)
        self.sidebar.setVisible(not reference_mode)
        self.manual_controls_container.setVisible(not reference_mode)
        self.apply_changes_button.setVisible(reference_mode)
        self.undo_button.setVisible(not reference_mode)
        self.revert_button.setVisible(not reference_mode)
        self.sidebar_heading.setText("Mastering" if not reference_mode else "Reference Match")

        if show_workspace:
            self.content_stack.setCurrentWidget(self.workspace_page)
            self.back_button.show()
        if not force and previous_mode != reference_mode and self.session_state.has_preview_results:
            self.revert_preview(status="Apply changes")
        if not reference_mode:
            self._load_live_track_for_selection()
        self._refresh_reference()
        self._refresh_track_ui()
        self._update_stepper_state()
        self._update_responsive_layouts()

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))

    def _selected_track_index(self) -> int:
        if not self.session_state.track_paths:
            return -1
        index = self.track_selector.currentIndex()
        if index < 0 or index >= len(self.session_state.track_paths):
            return 0
        return index

    def _selected_track_path(self) -> str | None:
        if not self.session_state.track_paths:
            return None
        return self.session_state.track_paths[self._selected_track_index()]

    def _selected_preview_path(self) -> str | None:
        if not self.session_state.preview_pairs:
            return None
        return self.session_state.preview_pairs[self._selected_track_index()].mastered_preview_path

    def _refresh_track_selector(self) -> None:
        was_blocked = self.track_selector.blockSignals(True)
        current_index = self._selected_track_index()
        self.track_selector.clear()
        self.track_selector.addItems([Path(path).name for path in self.session_state.track_paths])
        if self.session_state.track_paths:
            self.track_selector.setCurrentIndex(min(max(current_index, 0), len(self.session_state.track_paths) - 1))
        self.track_selector.setVisible(len(self.session_state.track_paths) > 1)
        self.track_selector.blockSignals(was_blocked)

    def _on_selected_track_changed(self, _index: int) -> None:
        self.stop_transport()
        self._load_live_track_for_selection()
        self._refresh_track_ui()

    def _refresh_reference(self) -> None:
        if self.session_state.reference_track_path is None:
            self.reference_zone.set_empty_state("Drop your reference track")
            self.reference_zone.select_button.setText("Upload Reference")
            self.reference_track_zone.select_button.setText("Upload Track")
            self.reference_track_zone.select_button.setDisabled(True)
            self.reference_track_zone.set_empty_state("Drop your track to master")
            self.reference_track_zone.detail_label.setText("Add a reference first")
            self._update_stepper_state()
            return

        self.reference_zone.set_empty_state(Path(self.session_state.reference_track_path).name)
        self.reference_zone.select_button.setText("Replace Reference")
        self.reference_track_zone.select_button.setDisabled(False)
        self.reference_track_zone.detail_label.setText("The track to be mastered")
        self._update_stepper_state()

    def _refresh_track_ui(self) -> None:
        track_path = self._selected_track_path()
        preview_path = self._selected_preview_path()
        track_count = len(self.session_state.track_paths)
        self._refresh_track_selector()

        if track_path is None:
            self.stop_transport()
            self.track_name_chip.setText("")
            self.original_file_label.setText("")
            self.mastered_file_label.setText("")
            self.original_waveform.set_display_text("Original")
            self.mastered_waveform.set_display_text("Mastered")
            self.original_upload_button.setText("Upload Track")
            self.manual_track_zone.set_empty_state("Drop your track here")
            self.reference_track_zone.set_empty_state("Drop your track to master")
            self.original_waveform.set_peaks([])
            self.mastered_waveform.set_peaks([])
            self._update_playhead_visuals(0.0)
            self.download_button.setDisabled(True)
            self._sync_transport_buttons()
            self._update_stepper_state()
            return

        if track_count > 1:
            self.track_name_chip.setText(f"Album - {track_count} Tracks")
        else:
            self.track_name_chip.setText(Path(track_path).name)
        self.original_file_label.setText(Path(track_path).name)
        self.manual_track_zone.set_empty_state(Path(track_path).name)
        self.reference_track_zone.set_empty_state(Path(track_path).name)
        self.original_waveform.set_display_text(self._track_overlay_text())
        self.original_upload_button.setText("Replace Tracks" if track_count > 1 else "Replace Track")
        self.download_button.setDisabled(
            self.live_track is None or (self.reference_mode_button.isChecked() and preview_path is None)
        )
        if self.live_track is None:
            self.mastered_file_label.setText(Path(preview_path).name if preview_path else Path(track_path).name)
            self.mastered_waveform.set_display_text("Mastered")
            self.original_waveform.set_peaks([])
            self.mastered_waveform.set_peaks([])
            self._update_playhead_visuals(0.0)
            self._sync_transport_buttons()
            self._update_stepper_state()
            return

        self.original_waveform.set_peaks(self.live_track.original_waveform)
        self.mastered_waveform.set_peaks(self.live_track.mastered_waveform)
        self.mastered_waveform.set_display_text("Mastered")
        if self.reference_mode_button.isChecked() and preview_path is not None:
            self.mastered_file_label.setText(Path(preview_path).name)
        else:
            self.mastered_file_label.setText(Path(track_path).name)
        self._sync_transport_buttons()
        self._update_stepper_state()

    def _set_busy(self, busy: bool) -> None:
        self.reference_mode_button.setDisabled(busy)
        self.manual_mode_button.setDisabled(busy)
        self.reference_zone.select_button.setDisabled(busy)
        self.reference_track_zone.select_button.setDisabled(busy or self.session_state.reference_track_path is None)
        self.original_upload_button.setDisabled(busy)
        self.apply_changes_button.setDisabled(busy)
        self.undo_button.setDisabled(busy)
        self.memory_combo.setDisabled(busy)
        self.save_memory_button.setDisabled(busy)
        self.revert_button.setDisabled(busy)
        self.download_button.setDisabled(busy or self.live_track is None)
        if busy:
            self.transport_play_button.setDisabled(True)
            self.transport_stop_button.setDisabled(True)
            self.original_listen_button.setDisabled(True)
            self.mastered_listen_button.setDisabled(True)
        else:
            self._sync_transport_buttons()
        self._update_stepper_state()

    def _refresh_memory_combo(self, *, selected_name: str | None = None) -> None:
        names = self.preset_store.list_names()
        was_blocked = self.memory_combo.blockSignals(True)
        self.memory_combo.clear()
        self.memory_combo.addItem("Memories")
        self.memory_combo.addItems(names)
        if selected_name and selected_name in names:
            self.memory_combo.setCurrentText(selected_name)
        else:
            self.memory_combo.setCurrentIndex(0)
        self.memory_combo.blockSignals(was_blocked)

    def _on_memory_selected(self, name: str) -> None:
        if not name or name == "Memories":
            return
        self.load_selected_memory()

    def _prepare_preview_directory(self) -> str:
        preview_dir = self.preview_root / "current-preview"
        if preview_dir.exists():
            shutil.rmtree(preview_dir, ignore_errors=True)
        preview_dir.mkdir(parents=True, exist_ok=True)
        return str(preview_dir)

    def _track_overlay_text(self) -> str:
        if self.live_track is None:
            track_path = self._selected_track_path()
            if track_path is None:
                return "Original"
            return f"Original - {Path(track_path).name}"
        bpm_text = f"{int(round(self.live_track.estimated_bpm))} BPM" if self.live_track.estimated_bpm else "-- BPM"
        return f"Original - {Path(self.live_track.path).name} - {bpm_text}"

    def _update_playhead_visuals(self, progress: float) -> None:
        self.original_waveform.set_playhead_progress(progress)
        self.mastered_waveform.set_playhead_progress(progress)
        was_blocked = self.position_slider.blockSignals(True)
        self.position_slider.setValue(int(round(progress * 1000)))
        self.position_slider.blockSignals(was_blocked)

    def _total_audio_bytes(self) -> int:
        return self.audio_device.source_length("original")

    def _seek_from_slider(self, slider_value: int) -> None:
        total_bytes = self._total_audio_bytes()
        if total_bytes <= 0:
            self._update_playhead_visuals(0.0)
            return

        bytes_per_frame = max(1, self.audio_format.bytesPerFrame())
        byte_offset = int((slider_value / 1000.0) * total_bytes)
        byte_offset -= byte_offset % bytes_per_frame
        self.audio_device.seek_to(byte_offset)
        self._update_playhead_visuals(byte_offset / total_bytes)

    def _update_transport_position(self) -> None:
        total_bytes = self._total_audio_bytes()
        if total_bytes <= 0:
            self._update_playhead_visuals(0.0)
            return
        self._update_playhead_visuals(self.audio_device.current_position() / total_bytes)

    def _sync_transport_buttons(self) -> None:
        has_live_audio = self.live_track is not None and self.live_track.original_audio.size > 0
        self.transport_play_button.setText(
            "Pause" if self.transport_state == "playing" else "Resume" if self.transport_state == "paused" else "Play"
        )
        self.transport_play_button.setDisabled(not has_live_audio)
        self.transport_stop_button.setDisabled(not has_live_audio or self.transport_state == "stopped")
        self.position_slider.setDisabled(not has_live_audio)
        self.original_listen_button.setDisabled(not has_live_audio)
        self.mastered_listen_button.setDisabled(not has_live_audio)
        self.original_listen_button.setChecked(self.active_source == "original")
        self.mastered_listen_button.setChecked(self.active_source == "mastered")
        self.original_waveform.set_active(self.active_source == "original")
        self.mastered_waveform.set_active(self.active_source == "mastered")

    def pick_tracks(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Choose audio files",
            "",
            self.audio_file_filter,
        )
        if files:
            self.import_tracks(files)

    def pick_reference_track(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a reference track",
            "",
            self.audio_file_filter,
        )
        if file_path:
            self.import_reference_tracks([file_path])

    def _load_live_track_for_selection(self) -> None:
        track_path = self._selected_track_path()
        self.live_track = None
        self.audio_device.set_source_bytes("original", b"")
        self.audio_device.set_source_bytes("mastered", b"")
        self._update_playhead_visuals(0.0)
        if track_path is None or not Path(track_path).exists():
            self._sync_transport_buttons()
            return

        live_track = load_live_audio_track(track_path)
        self.live_track = live_track
        target_level = max(-24.0, min(0.0, live_track.source_level_db))
        self.controls.target_lufs = target_level
        self.committed_controls = replace(self.controls)
        self._sync_control_widgets()
        self._set_active_source("original")
        self._update_audio_buffers()

    def _update_audio_buffers(self) -> None:
        if self.live_track is None:
            self.audio_device.set_source_bytes("original", b"")
            self.audio_device.set_source_bytes("mastered", b"")
            return

        self.audio_device.set_source_bytes("original", pcm16le_bytes(self.live_track.original_audio))
        self.audio_device.set_source_bytes("mastered", pcm16le_bytes(self.live_track.mastered_audio))

    def _schedule_live_render(self) -> None:
        if self.reference_mode_button.isChecked() or self.live_track is None:
            return
        self.live_render_timer.start(120)
        self._set_status("Updating master")

    def _start_live_render(self) -> None:
        if self.live_track is None or self.reference_mode_button.isChecked():
            return
        if self.live_render_worker is not None:
            self.pending_live_controls = replace(self.controls)
            return

        self.live_render_worker = LiveMasteringWorker(
            original_audio=self.live_track.original_audio,
            controls=replace(self.controls),
            source_level_db=self.live_track.source_level_db,
        )
        self.live_render_worker.completed.connect(self._on_live_render_completed)
        self.live_render_worker.failed.connect(self._on_live_render_failed)
        self.live_render_worker.start()

    def _on_live_render_completed(self, mastered_audio, waveform) -> None:
        if self.live_track is not None:
            self.live_track.mastered_audio = mastered_audio
            self.live_track.mastered_waveform = list(waveform)
            self.mastered_waveform.set_peaks(self.live_track.mastered_waveform)
            self._update_audio_buffers()

        self.live_render_worker = None
        if self.pending_live_controls is not None and self.pending_live_controls != self.controls:
            self.pending_live_controls = None
            self._schedule_live_render()
            return
        self.pending_live_controls = None
        self._set_status("")
        self._sync_transport_buttons()

    def _on_live_render_failed(self, _error_message: str) -> None:
        self.live_render_worker = None
        self.pending_live_controls = None
        self._set_status("Unable to update master")
        self._sync_transport_buttons()

    def _set_active_source(self, source: str) -> None:
        self.active_source = source
        self.audio_device.set_active_source(source)
        self._sync_transport_buttons()

    def toggle_transport_playback(self) -> None:
        if self.live_track is None:
            return

        if self.transport_state == "playing":
            self.audio_sink.suspend()
            self.position_timer.stop()
            self.transport_state = "paused"
        elif self.transport_state == "paused":
            self.audio_sink.resume()
            self.position_timer.start()
            self.transport_state = "playing"
        else:
            if not self.audio_device.isOpen():
                self.audio_device.start()
            self.audio_sink.start(self.audio_device)
            self.position_timer.start()
            self.transport_state = "playing"
        self._sync_transport_buttons()

    def stop_transport(self) -> None:
        self.audio_sink.stop()
        self.audio_device.stop()
        self.position_timer.stop()
        self.transport_state = "stopped"
        self._update_playhead_visuals(0.0)
        self._sync_transport_buttons()

    def _on_audio_state_changed(self, state) -> None:
        if state == QAudio.State.IdleState:
            self.stop_transport()

    def import_tracks(self, paths: list[str]) -> None:
        accepted = accepted_audio_paths(paths, max_items=MAX_TRACKS)
        if not accepted:
            self._set_status("Unsupported track")
            return

        if self.content_stack.currentWidget() is self.home_page:
            self._sync_mode_ui(reference_mode=False)
        self.stop_transport()
        self.session_state.track_paths = accepted
        self.session_state.clear_preview_outputs()
        self.track_selector.setCurrentIndex(0)
        self._load_live_track_for_selection()
        self._refresh_track_ui()
        self._set_status("Track loaded")

    def import_reference_tracks(self, paths: list[str]) -> None:
        if not paths:
            self._set_status("")
            return

        if self.content_stack.currentWidget() is self.home_page:
            self._sync_mode_ui(reference_mode=True)
        if not self.session_state.set_reference_track(paths[0]):
            self._set_status("Unsupported track")
            return

        self.stop_transport()
        self._refresh_reference()
        if self.reference_mode_button.isChecked():
            self._load_live_track_for_selection()
        self._refresh_track_ui()
        self._set_status("Track loaded")

    def _begin_apply_state(self) -> None:
        self.stop_transport()
        self._set_busy(True)
        self._set_status("Applying changes")

    def start_mastering(self) -> None:
        if not self.session_state.track_paths:
            self._set_status("Upload track")
            return

        reference_mode = self.reference_mode_button.isChecked()
        if not reference_mode:
            return
        if reference_mode and self.session_state.reference_track_path is None:
            self._set_status("Upload reference")
            return

        self._begin_apply_state()
        self.worker = MasteringWorker(
            reference_mode=reference_mode,
            track_paths=list(self.session_state.track_paths),
            preview_directory=self._prepare_preview_directory(),
            controls=replace(self.controls),
            reference_track_path=self.session_state.reference_track_path,
        )
        self.worker.completed.connect(self._on_mastering_completed)
        self.worker.failed.connect(self._on_mastering_failed)
        self.worker.start()

    def _on_mastering_completed(self, output_paths: list[str]) -> None:
        self.session_state.register_preview_outputs(output_paths)
        preview_path = self._selected_preview_path()
        if self.live_track is not None and preview_path and Path(preview_path).exists():
            mastered_audio = decode_audio_file(preview_path, sample_rate=self.live_track.sample_rate)
            self.live_track.mastered_audio = mastered_audio
            self.live_track.mastered_waveform = build_waveform_peaks(mastered_audio)
            self._update_audio_buffers()
        self.committed_controls = replace(self.controls)
        self._refresh_track_ui()
        self._set_busy(False)
        self._set_status("Preview ready")
        self.worker = None

    def _on_mastering_failed(self, error_message: str) -> None:
        self._set_busy(False)
        self._set_status("Unable to apply changes")
        self.worker = None

    def play_original_track(self) -> None:
        self._set_active_source("original")
        self.toggle_transport_playback()

    def play_mastered_preview(self) -> None:
        self._set_active_source("mastered")
        self.toggle_transport_playback()

    def stop_original_track(self) -> None:
        if self.active_source == "original":
            self.stop_transport()

    def stop_mastered_track(self) -> None:
        if self.active_source == "mastered":
            self.stop_transport()

    def stop_preview(self) -> None:
        self.stop_transport()

    def revert_preview(self, status: str = "Reverted") -> None:
        self.stop_transport()
        self.session_state.clear_preview_outputs()
        if self.live_track is not None:
            self.live_track.mastered_audio = self.live_track.original_audio.copy()
            self.live_track.mastered_waveform = list(self.live_track.original_waveform)
            self.mastered_waveform.set_peaks(self.live_track.mastered_waveform)
            self._update_audio_buffers()
        self._refresh_track_ui()
        self._set_status(status)

    def save_mastered_tracks(self) -> None:
        if not self.session_state.output_directory:
            directory = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if not directory:
                self._set_status("")
                return
            self.session_state.output_directory = directory

        if self.reference_mode_button.isChecked():
            if not self.session_state.has_preview_results:
                self._set_status("Apply")
                return
            saved_paths = save_mastered_previews(
                preview_paths=[pair.mastered_preview_path for pair in self.session_state.preview_pairs],
                source_paths=[pair.original_path for pair in self.session_state.preview_pairs],
                output_directory=self.session_state.output_directory,
            )
            if saved_paths:
                self._set_status("Saved")
            return

        if self.live_track is None:
            self._set_status("Upload track")
            return

        import soundfile as sf

        output_path = Path(self.session_state.output_directory) / f"{Path(self.live_track.path).stem}-master.wav"
        sf.write(str(output_path), self.live_track.mastered_audio, self.live_track.sample_rate, subtype="PCM_16")
        self._set_status("Saved")

    def undo_control_changes(self) -> None:
        self._apply_controls(self.committed_controls, announce=False)
        self._set_status("Changes undone")

    def save_current_memory(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save Memory", "Name")
        if not accepted:
            return

        cleaned_name = name.strip()
        if not cleaned_name:
            return

        self.preset_store.save_preset(cleaned_name, self.controls)
        self._refresh_memory_combo(selected_name=cleaned_name)
        self._set_status("Memory saved")

    def load_selected_memory(self) -> None:
        name = self.memory_combo.currentText().strip()
        if not name or name == "Memories":
            return

        preset = self.preset_store.load_preset(name)
        if preset is None:
            return

        style_blocked = self.style_combo.blockSignals(True)
        self.style_combo.setCurrentText("Custom")
        self.style_combo.blockSignals(style_blocked)
        self.style_intensity_slider.setEnabled(False)
        self._apply_controls(preset, announce=False)
        self.committed_controls = replace(self.controls)
        self._set_status("Memory loaded")

    def _update_control(self, attribute: str, value) -> None:
        if getattr(self.controls, attribute) == value:
            return

        setattr(self.controls, attribute, value)
        if self.memory_combo.currentText() != "Memories":
            was_blocked = self.memory_combo.blockSignals(True)
            self.memory_combo.setCurrentIndex(0)
            self.memory_combo.blockSignals(was_blocked)
        if not self._applying_style and attribute != "reference_strength_percent" and self.style_combo.currentText() != "Custom":
            was_blocked = self.style_combo.blockSignals(True)
            self.style_combo.setCurrentText("Custom")
            self.style_combo.blockSignals(was_blocked)
            self.style_intensity_slider.setEnabled(False)
            self._sync_quick_preset_buttons("Custom")
        if not self.reference_mode_button.isChecked():
            self._schedule_live_render()
        elif self.session_state.has_preview_results:
            self.revert_preview(status="Apply changes")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.stop_preview()
        if self.live_render_worker is not None:
            self.live_render_worker.wait(1000)
        shutil.rmtree(self.preview_root, ignore_errors=True)
        super().closeEvent(event)


def create_application() -> QApplication:
    app = QApplication.instance()
    if app is not None:
        return app

    app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName("Music Mastery")
    app.setApplicationDisplayName("Music Mastery")
    return app
