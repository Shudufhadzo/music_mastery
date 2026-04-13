import AppKit
import AVFoundation
import Foundation
import MusicMasteryCore
import SwiftUI

enum MasteringMode: String {
    case reference
    case manual
}

enum ActiveSource: String {
    case original
    case mastered
}

struct PreviewPair: Identifiable, Equatable {
    var originalURL: URL
    var masteredPreviewURL: URL

    var id: String {
        originalURL.path
    }
}

@MainActor
final class MasteringViewModel: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var mode: MasteringMode?
    @Published var trackURLs: [URL] = []
    @Published var referenceURL: URL?
    @Published var outputDirectory: URL?
    @Published var selectedTrackIndex = 0
    @Published var controls = MasteringControls()
    @Published var committedControls = MasteringControls()
    @Published var liveTrack: LiveAudioTrack?
    @Published var previewPairs: [PreviewPair] = []
    @Published var statusMessage = ""
    @Published var activeSource: ActiveSource = .original
    @Published var isBusy = false
    @Published var isRendering = false
    @Published var isPlaying = false
    @Published var playheadProgress = 0.0
    @Published var memoryNames: [String] = []
    @Published var selectedMemoryName = "Memories"
    @Published var styleName = "Custom"
    @Published var styleIntensity = 60

    let presetNames = ["Warm", "Punch", "Clean", "Bright"]

    private let presetStore = MasteringPresetStore()
    private let tempRoot: URL
    private var trackLoadTask: Task<Void, Never>?
    private var renderTask: Task<Void, Never>?
    private var player: AVAudioPlayer?
    private var progressTimer: Timer?
    private var isApplyingStyle = false

    override init() {
        tempRoot = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
            .appendingPathComponent("music-mastery-macos-\(UUID().uuidString)", isDirectory: true)
        super.init()
        try? FileManager.default.createDirectory(at: tempRoot, withIntermediateDirectories: true)
        refreshMemoryNames()
    }

    deinit {
        trackLoadTask?.cancel()
        renderTask?.cancel()
        progressTimer?.invalidate()
        try? FileManager.default.removeItem(at: tempRoot)
    }

    var isHome: Bool {
        mode == nil
    }

    var selectedTrackURL: URL? {
        guard !trackURLs.isEmpty else {
            return nil
        }
        return trackURLs[min(max(selectedTrackIndex, 0), trackURLs.count - 1)]
    }

    var selectedPreviewURL: URL? {
        guard !previewPairs.isEmpty else {
            return nil
        }
        return previewPairs[min(max(selectedTrackIndex, 0), previewPairs.count - 1)].masteredPreviewURL
    }

    var canApplyReference: Bool {
        mode == .reference && referenceURL != nil && !trackURLs.isEmpty && !isBusy
    }

    var canExport: Bool {
        guard liveTrack != nil else {
            return false
        }
        if mode == .reference {
            return selectedPreviewURL != nil
        }
        return true
    }

    var trackTitle: String {
        guard let selectedTrackURL else {
            return ""
        }
        if trackURLs.count > 1 {
            return "Album - \(trackURLs.count) Tracks"
        }
        return selectedTrackURL.lastPathComponent
    }

    var originalOverlayText: String {
        guard let liveTrack else {
            return "Original"
        }
        let bpm = liveTrack.estimatedBpm.map { "\(Int(round($0))) BPM" } ?? "-- BPM"
        return "Original - \(liveTrack.url.lastPathComponent) - \(bpm)"
    }

    func start(_ nextMode: MasteringMode) {
        mode = nextMode
        if nextMode == .manual, selectedTrackURL != nil {
            scheduleSelectedTrackLoad()
        }
    }

    func showHome() {
        stopPlayback()
        mode = nil
    }

    func importTracks(_ urls: [URL]) {
        let accepted = acceptedAudioURLs(urls, maxItems: maxTrackCount)
        guard !accepted.isEmpty else {
            setStatus("Unsupported track")
            return
        }

        if mode == nil {
            mode = .manual
        }

        stopPlayback()
        trackURLs = accepted
        selectedTrackIndex = 0
        previewPairs = []
        scheduleSelectedTrackLoad()
    }

    func importReference(_ urls: [URL]) {
        guard let accepted = acceptedAudioURLs(urls, maxItems: 1).first else {
            setStatus("Unsupported track")
            return
        }

        if mode == nil {
            mode = .reference
        }

        stopPlayback()
        referenceURL = accepted
        previewPairs = []
        setStatus("Track loaded")
    }

    func selectTrack(index: Int) {
        guard index >= 0, index < trackURLs.count else {
            return
        }
        selectedTrackIndex = index
        scheduleSelectedTrackLoad()
    }

    func setControl<Value: Equatable>(
        _ keyPath: WritableKeyPath<MasteringControls, Value>,
        _ value: Value,
        resetsStyle: Bool = true
    ) {
        guard controls[keyPath: keyPath] != value else {
            return
        }

        controls[keyPath: keyPath] = value
        selectedMemoryName = "Memories"

        if resetsStyle, !isApplyingStyle, styleName != "Custom" {
            styleName = "Custom"
        }

        if mode == .manual {
            scheduleManualRender()
        } else if !previewPairs.isEmpty {
            previewPairs = []
            resetMasteredToOriginal()
            setStatus("Apply changes")
        }
    }

    func setReferenceStrength(_ value: Int) {
        setControl(\.referenceStrengthPercent, value, resetsStyle: false)
    }

    func setQuickStyle(_ name: String) {
        styleName = name
        applySelectedStyle()
    }

    func setStyleIntensity(_ value: Int) {
        styleIntensity = value
        if styleName != "Custom" {
            applySelectedStyle()
        }
    }

    func applySelectedStyle() {
        guard styleName != "Custom" else {
            return
        }

        var nextControls = styledControls(styleName: styleName, intensityPercent: styleIntensity)
        nextControls.gainDb = controls.gainDb
        nextControls.targetLufs = controls.targetLufs
        nextControls.referenceStrengthPercent = controls.referenceStrengthPercent

        isApplyingStyle = true
        controls = nextControls
        isApplyingStyle = false

        if mode == .manual {
            scheduleManualRender()
        } else if !previewPairs.isEmpty {
            previewPairs = []
            resetMasteredToOriginal()
            setStatus("Apply changes")
        }
    }

    func applyReferenceMatch() {
        guard let referenceURL, !trackURLs.isEmpty else {
            setStatus(referenceURL == nil ? "Upload reference" : "Upload track")
            return
        }

        stopPlayback()
        isBusy = true
        setStatus("Applying changes")

        let inputURLs = trackURLs
        let controls = controls
        let previewDirectory = preparePreviewDirectory()
        Task { [weak self] in
            do {
                let outputURLs = try await Task.detached(priority: .userInitiated) {
                    try AudioMasteringEngine.runReferenceMatch(
                        inputURLs: inputURLs,
                        referenceURL: referenceURL,
                        outputDirectory: previewDirectory,
                        controls: controls,
                        preview: true
                    )
                }.value

                guard let self else {
                    return
                }

                previewPairs = zip(inputURLs, outputURLs).map {
                    PreviewPair(originalURL: $0.0, masteredPreviewURL: $0.1)
                }
                if let previewURL = selectedPreviewURL {
                    let masteredAudio = try await Task.detached(priority: .userInitiated) {
                        try AudioMasteringEngine.decodeAudioFile(previewURL)
                    }.value
                    updateMasteredAudio(masteredAudio)
                }
                committedControls = controls
                isBusy = false
                setStatus("Preview ready")
            } catch {
                self?.isBusy = false
                self?.setStatus("Unable to apply changes")
            }
        }
    }

    func undoControlChanges() {
        controls = committedControls
        if mode == .manual {
            scheduleManualRender()
        } else {
            resetMasteredToOriginal()
        }
        setStatus("Changes undone")
    }

    func resetPreview() {
        stopPlayback()
        previewPairs = []
        resetMasteredToOriginal()
        setStatus("Reverted")
    }

    func saveMemory(named name: String) {
        do {
            try presetStore.savePreset(named: name, controls: controls)
            refreshMemoryNames(selectedName: name.trimmingCharacters(in: .whitespacesAndNewlines))
            setStatus("Memory saved")
        } catch {
            setStatus("Name required")
        }
    }

    func loadMemory(named name: String) {
        guard name != "Memories", let preset = presetStore.loadPreset(named: name) else {
            return
        }
        selectedMemoryName = name
        styleName = "Custom"
        controls = preset
        committedControls = preset
        if mode == .manual {
            scheduleManualRender()
        } else if !previewPairs.isEmpty {
            previewPairs = []
            resetMasteredToOriginal()
            setStatus("Apply changes")
        }
        setStatus("Memory loaded")
    }

    func selectSource(_ source: ActiveSource) {
        let resumeTime = player?.currentTime ?? 0
        let wasPlaying = isPlaying
        activeSource = source

        guard wasPlaying else {
            return
        }

        startPlayback(at: resumeTime)
    }

    func togglePlayback() {
        if isPlaying {
            player?.pause()
            isPlaying = false
            stopProgressTimer()
            return
        }

        startPlayback(at: player?.currentTime ?? 0)
    }

    func stopPlayback() {
        player?.stop()
        player = nil
        isPlaying = false
        playheadProgress = 0
        stopProgressTimer()
    }

    func seek(to progress: Double) {
        playheadProgress = max(0, min(1, progress))
        guard let player else {
            return
        }
        player.currentTime = playheadProgress * player.duration
    }

    func chooseOutputAndExport() {
        let panel = NSOpenPanel()
        panel.title = "Choose output folder"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else {
                return
            }
            Task { @MainActor in
                self?.export(to: url)
            }
        }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            self?.stopPlayback()
        }
    }

    private func refreshMemoryNames(selectedName: String? = nil) {
        memoryNames = presetStore.listNames()
        if let selectedName, memoryNames.contains(selectedName) {
            selectedMemoryName = selectedName
        } else {
            selectedMemoryName = "Memories"
        }
    }

    private func scheduleSelectedTrackLoad() {
        trackLoadTask?.cancel()
        guard selectedTrackURL != nil else {
            liveTrack = nil
            isBusy = false
            setStatus("")
            return
        }

        Task { @MainActor [weak self] in
            await Task.yield()
            self?.loadSelectedTrack()
        }
    }

    private func loadSelectedTrack() {
        guard let selectedTrackURL else {
            trackLoadTask?.cancel()
            liveTrack = nil
            isBusy = false
            return
        }

        trackLoadTask?.cancel()
        stopPlayback()
        isBusy = true
        setStatus("Loading track")

        trackLoadTask = Task { [weak self] in
            do {
                let loadedTrack = try await Task.detached(priority: .userInitiated) {
                    try AudioMasteringEngine.loadLiveAudioTrack(selectedTrackURL)
                }.value

                guard let self, !Task.isCancelled, self.selectedTrackURL == selectedTrackURL else {
                    return
                }

                liveTrack = loadedTrack
                let targetLevel = max(-24.0, min(0.0, loadedTrack.sourceLevelDb))
                controls.targetLufs = targetLevel
                committedControls = controls

                if mode == .reference, let previewURL = selectedPreviewURL {
                    let masteredAudio = try await Task.detached(priority: .userInitiated) {
                        try AudioMasteringEngine.decodeAudioFile(previewURL)
                    }.value
                    updateMasteredAudio(masteredAudio)
                } else {
                    resetMasteredToOriginal()
                }

                try writeCurrentMasteredFile()
                isBusy = false
                setStatus("Track loaded")
            } catch {
                guard let self, !Task.isCancelled, self.selectedTrackURL == selectedTrackURL else {
                    return
                }
                self.isBusy = false
                self.liveTrack = nil
                self.setStatus("Unable to load track")
            }
        }
    }

    private func scheduleManualRender() {
        guard mode == .manual, let liveTrack else {
            return
        }

        renderTask?.cancel()
        isRendering = true
        setStatus("Updating master")

        let originalAudio = liveTrack.originalAudio
        let sourceLevelDb = liveTrack.sourceLevelDb
        let controls = controls

        renderTask = Task { [weak self] in
            do {
                try await Task.sleep(nanoseconds: 120_000_000)
                let masteredAudio = await Task.detached(priority: .userInitiated) {
                    AudioMasteringEngine.applyLiveMastering(
                        originalAudio,
                        controls: controls,
                        sourceLevelDb: sourceLevelDb
                    )
                }.value

                guard !Task.isCancelled, let self else {
                    return
                }

                updateMasteredAudio(masteredAudio)
                try writeCurrentMasteredFile()
                isRendering = false
                setStatus("")
            } catch is CancellationError {
                self?.isRendering = false
            } catch {
                self?.isRendering = false
                self?.setStatus("Unable to update master")
            }
        }
    }

    private func updateMasteredAudio(_ masteredAudio: StereoAudio) {
        guard var liveTrack else {
            return
        }

        liveTrack.masteredAudio = masteredAudio
        liveTrack.masteredWaveform = AudioMasteringEngine.buildWaveformPeaks(masteredAudio)
        self.liveTrack = liveTrack
    }

    private func resetMasteredToOriginal() {
        guard var liveTrack else {
            return
        }

        liveTrack.masteredAudio = liveTrack.originalAudio
        liveTrack.masteredWaveform = liveTrack.originalWaveform
        self.liveTrack = liveTrack
        try? writeCurrentMasteredFile()
    }

    private func preparePreviewDirectory() -> URL {
        let directory = tempRoot.appendingPathComponent("current-preview", isDirectory: true)
        if FileManager.default.fileExists(atPath: directory.path) {
            try? FileManager.default.removeItem(at: directory)
        }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private func currentMasteredURL() -> URL {
        let stem = selectedTrackURL?.deletingPathExtension().lastPathComponent ?? "current"
        return tempRoot.appendingPathComponent("\(stem)-master-preview.wav")
    }

    private func writeCurrentMasteredFile() throws {
        guard let liveTrack else {
            return
        }
        try AudioMasteringEngine.writeWAV(liveTrack.masteredAudio, to: currentMasteredURL(), bitDepth: 16)
    }

    private func sourceURL(for source: ActiveSource) -> URL? {
        switch source {
        case .original:
            return selectedTrackURL
        case .mastered:
            if mode == .reference {
                return selectedPreviewURL
            }
            return currentMasteredURL()
        }
    }

    private func startPlayback(at requestedTime: TimeInterval) {
        guard let url = sourceURL(for: activeSource), FileManager.default.fileExists(atPath: url.path) else {
            setStatus("Nothing to play")
            return
        }

        do {
            player?.stop()
            let nextPlayer = try AVAudioPlayer(contentsOf: url)
            nextPlayer.delegate = self
            nextPlayer.currentTime = min(max(0, requestedTime), nextPlayer.duration)
            nextPlayer.prepareToPlay()
            nextPlayer.play()
            player = nextPlayer
            isPlaying = true
            startProgressTimer()
        } catch {
            setStatus("Unable to play track")
        }
    }

    private func startProgressTimer() {
        stopProgressTimer()
        progressTimer = Timer.scheduledTimer(withTimeInterval: 0.04, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self, let player = self.player, player.duration > 0 else {
                    return
                }
                self.playheadProgress = player.currentTime / player.duration
            }
        }
    }

    private func stopProgressTimer() {
        progressTimer?.invalidate()
        progressTimer = nil
    }

    private func export(to directory: URL) {
        outputDirectory = directory
        do {
            if mode == .reference {
                guard !previewPairs.isEmpty else {
                    setStatus("Apply")
                    return
                }
                _ = try AudioMasteringEngine.saveMasteredPreviews(
                    previewURLs: previewPairs.map(\.masteredPreviewURL),
                    sourceURLs: previewPairs.map(\.originalURL),
                    outputDirectory: directory
                )
                setStatus("Saved")
                return
            }

            guard let liveTrack else {
                setStatus("Upload track")
                return
            }

            let outputURL = directory.appendingPathComponent(liveTrack.url.deletingPathExtension().lastPathComponent + "-master.wav")
            try AudioMasteringEngine.writeWAV(liveTrack.masteredAudio, to: outputURL, bitDepth: 16)
            setStatus("Saved")
        } catch {
            setStatus("Unable to save")
        }
    }

    private func setStatus(_ message: String) {
        statusMessage = message
    }
}
