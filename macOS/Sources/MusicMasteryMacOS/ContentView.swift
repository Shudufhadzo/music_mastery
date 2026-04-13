import MusicMasteryCore
import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: MasteringViewModel
    @State private var memoryName = ""

    var body: some View {
        ZStack {
            Color.masteryBackground.ignoresSafeArea()

            VStack(spacing: 18) {
                HeaderView()

                if model.isHome {
                    HomeView()
                } else {
                    WorkspaceView(memoryName: $memoryName)
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 18)
        }
        .foregroundStyle(Color.masteryText)
    }
}

private struct HeaderView: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        HStack(spacing: 14) {
            if !model.isHome {
                Button {
                    model.showHome()
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 17, weight: .bold))
                        .frame(width: 36, height: 36)
                }
                .buttonStyle(.plain)
                .background(Color.masteryPanel)
                .clipShape(Circle())
                .accessibilityLabel("Back")
            }

            Text("M")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Color.masteryAccent)
                .frame(width: 44, height: 44)
                .background(Color.masteryAccent.opacity(0.14))
                .clipShape(Circle())

            Text("Music Mastery")
                .font(.system(size: 22, weight: .bold))

            Spacer()
        }
    }
}

private struct HomeView: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 30)

            Text("Professional mastering made simple")
                .font(.system(size: 52, weight: .heavy))
                .multilineTextAlignment(.center)

            Text("Choose how you want to master your track.")
                .font(.title3)
                .foregroundStyle(Color.masteryMuted)

            HStack(spacing: 22) {
                Spacer()
                ModeCard(
                    title: "Match a Reference",
                    detail: "Upload a polished song and match your track to its sound.",
                    symbol: "R"
                ) {
                    model.start(.reference)
                }

                ModeCard(
                    title: "Manual Controls",
                    detail: "Shape your track with simple live sliders and compare instantly.",
                    symbol: "M"
                ) {
                    model.start(.manual)
                }
                Spacer()
            }

            Text("Reference matching is great for beginners.")
                .foregroundStyle(Color.masteryMuted)

            Spacer(minLength: 30)
        }
    }
}

private struct ModeCard: View {
    var title: String
    var detail: String
    var symbol: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 14) {
                Text(symbol)
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color.masteryAccent)
                    .frame(width: 56, height: 56)
                    .background(Color.white.opacity(0.05))
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                Text(title)
                    .font(.title3.weight(.bold))

                Text(detail)
                    .foregroundStyle(Color.masteryMuted)
                    .multilineTextAlignment(.leading)

                Spacer()
            }
            .frame(width: 304, height: 190, alignment: .topLeading)
            .padding(28)
            .background(Color.masteryPanel)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(Color.masteryBorder, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

private struct WorkspaceView: View {
    @EnvironmentObject private var model: MasteringViewModel
    @Binding var memoryName: String

    var body: some View {
        HStack(alignment: .top, spacing: 24) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    StepperView()
                    UploadSection()

                    if model.mode == .reference {
                        ReferenceToolbar()
                    }

                    ComparePanel()

                    if !model.statusMessage.isEmpty {
                        Text(model.statusMessage)
                            .foregroundStyle(Color.masteryMuted)
                            .frame(minHeight: 28, alignment: .leading)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }

            if model.mode == .manual {
                if model.liveTrack != nil {
                    SidebarView(memoryName: $memoryName)
                        .frame(width: 370)
                } else {
                    ManualSidebarPlaceholder()
                        .frame(width: 370)
                }
            }
        }
    }
}

private struct StepperView: View {
    @EnvironmentObject private var model: MasteringViewModel

    var labels: [String] {
        model.mode == .reference ? ["Reference", "Your Track", "Compare"] : ["Upload", "Adjust", "Compare"]
    }

    var activeIndex: Int {
        if model.mode == .reference {
            if !model.previewPairs.isEmpty { return 2 }
            if !model.trackURLs.isEmpty { return 1 }
            return model.referenceURL == nil ? 0 : 1
        }
        return model.trackURLs.isEmpty ? 0 : 2
    }

    var completedCount: Int {
        if model.mode == .reference {
            if !model.previewPairs.isEmpty { return 3 }
            if !model.trackURLs.isEmpty { return 2 }
            if model.referenceURL != nil { return 1 }
            return 0
        }
        return model.trackURLs.isEmpty ? 0 : 1
    }

    var body: some View {
        HStack(spacing: 18) {
            Spacer()
            ForEach(labels.indices, id: \.self) { index in
                VStack(spacing: 8) {
                    Text("\(index + 1)")
                        .font(.headline.weight(.bold))
                        .frame(width: 44, height: 44)
                        .background(index < completedCount ? Color.masteryAccent : Color.clear)
                        .foregroundStyle(index < completedCount ? Color.black : (index == activeIndex ? Color.white : Color.masteryMuted))
                        .clipShape(Circle())
                        .overlay(
                            Circle()
                                .stroke(index <= activeIndex ? Color.masteryAccent : Color.masteryBorder, lineWidth: 2)
                        )
                    Text(labels[index])
                        .font(.headline)
                        .foregroundStyle(index <= activeIndex ? Color.white : Color.masteryMuted)
                }

                if index < labels.count - 1 {
                    Rectangle()
                        .fill(Color.masteryBorder)
                        .frame(width: 56, height: 2)
                }
            }
            Spacer()
        }
        .padding(.vertical, 8)
    }
}

private struct UploadSection: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        if model.mode == .reference {
            HStack(spacing: 18) {
                AudioDropZone(
                    title: "Reference Track",
                    emptyText: model.referenceURL?.lastPathComponent ?? "Drop your reference track",
                    buttonText: model.referenceURL == nil ? "Upload Reference" : "Replace Reference",
                    allowsMultipleSelection: false
                ) { urls in
                    model.importReference(urls)
                }

                AudioDropZone(
                    title: "Your Track",
                    emptyText: model.selectedTrackURL?.lastPathComponent ?? "Drop your track to master",
                    buttonText: model.trackURLs.count > 1 ? "Replace Tracks" : "Upload Track",
                    allowsMultipleSelection: true
                ) { urls in
                    model.importTracks(urls)
                }
                .disabled(model.referenceURL == nil)
                .opacity(model.referenceURL == nil ? 0.55 : 1)
            }
        } else {
            AudioDropZone(
                title: "Your Track",
                emptyText: model.selectedTrackURL?.lastPathComponent ?? "Drop your track here",
                buttonText: model.trackURLs.count > 1 ? "Replace Tracks" : "Upload Track",
                allowsMultipleSelection: true
            ) { urls in
                model.importTracks(urls)
            }
        }
    }
}

private struct ReferenceToolbar: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        HStack(spacing: 14) {
            Text("Reference Strength")
                .font(.headline)

            Slider(
                value: Binding(
                    get: { Double(model.controls.referenceStrengthPercent) },
                    set: { model.setReferenceStrength(Int($0.rounded())) }
                ),
                in: 0...100,
                step: 1
            )

            Text("\(model.controls.referenceStrengthPercent)%")
                .foregroundStyle(Color.masteryMuted)
                .frame(width: 48, alignment: .trailing)

            Button("Apply") {
                model.applyReferenceMatch()
            }
            .buttonStyle(AccentButtonStyle())
            .disabled(!model.canApplyReference)
        }
        .padding(16)
        .background(Color.masteryPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
    }
}

private struct ComparePanel: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Compare")
                    .font(.title3.weight(.bold))

                if !model.trackTitle.isEmpty {
                    Text(model.trackTitle)
                        .font(.headline)
                }

                if model.trackURLs.count > 1 {
                    Picker("", selection: Binding(get: { model.selectedTrackIndex }, set: { model.selectTrack(index: $0) })) {
                        ForEach(Array(model.trackURLs.enumerated()), id: \.offset) { index, url in
                            Text(url.lastPathComponent).tag(index)
                        }
                    }
                    .labelsHidden()
                    .frame(maxWidth: 360)
                }

                Spacer()
            }

            WaveformPanel(
                title: "Original",
                fileName: model.selectedTrackURL?.lastPathComponent ?? "",
                overlayText: model.originalOverlayText,
                peaks: model.liveTrack?.originalWaveform ?? [],
                isActive: model.activeSource == .original,
                playheadProgress: model.playheadProgress,
                accent: .masteryBlue,
                buttonTitle: "A"
            ) {
                model.selectSource(.original)
            }

            WaveformPanel(
                title: "Mastered",
                fileName: model.selectedPreviewURL?.lastPathComponent ?? model.selectedTrackURL?.lastPathComponent ?? "",
                overlayText: "Mastered",
                peaks: model.liveTrack?.masteredWaveform ?? [],
                isActive: model.activeSource == .mastered,
                playheadProgress: model.playheadProgress,
                accent: .masteryAccent,
                buttonTitle: "B"
            ) {
                model.selectSource(.mastered)
            }

            HStack(spacing: 12) {
                Slider(value: Binding(get: { model.playheadProgress }, set: { model.seek(to: $0) }), in: 0...1)
                    .disabled(model.liveTrack == nil)

                Button(model.isPlaying ? "Pause" : "Play") {
                    model.togglePlayback()
                }
                .buttonStyle(GhostButtonStyle())
                .disabled(model.liveTrack == nil)

                Button("Stop") {
                    model.stopPlayback()
                }
                .buttonStyle(GhostButtonStyle())
                .disabled(model.liveTrack == nil)

                Button("Reset") {
                    model.undoControlChanges()
                }
                .buttonStyle(GhostButtonStyle())
                .disabled(model.liveTrack == nil)

                Button("Export") {
                    model.chooseOutputAndExport()
                }
                .buttonStyle(AccentButtonStyle())
                .disabled(!model.canExport)
            }
        }
        .padding(22)
        .background(Color.masteryPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
    }
}

private struct WaveformPanel: View {
    var title: String
    var fileName: String
    var overlayText: String
    var peaks: [Float]
    var isActive: Bool
    var playheadProgress: Double
    var accent: Color
    var buttonTitle: String
    var action: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text(title)
                    .font(.headline)
                if !fileName.isEmpty {
                    Text(fileName)
                        .foregroundStyle(Color.masteryMuted)
                        .lineLimit(1)
                }
                Spacer()
                Button(buttonTitle, action: action)
                    .buttonStyle(SourceButtonStyle(isActive: isActive))
            }

            WaveformView(
                peaks: peaks,
                accent: accent,
                active: isActive,
                displayText: overlayText,
                playheadProgress: playheadProgress
            )
            .frame(height: 78)
        }
        .padding(18)
        .background(Color.masteryRaisedPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct SidebarView: View {
    @EnvironmentObject private var model: MasteringViewModel
    @Binding var memoryName: String

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Mastering")
                    .font(.title3.weight(.bold))

                Text("Quick Presets")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color.masteryMuted)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                    ForEach(model.presetNames, id: \.self) { name in
                        Button(name == "Punch" ? "Punchy" : name == "Clean" ? "Balanced" : name) {
                            model.setQuickStyle(name)
                        }
                        .buttonStyle(ChipButtonStyle(isSelected: model.styleName == name))
                    }
                }

                ControlSlider(
                    title: "Preset Strength",
                    valueText: "\(model.styleIntensity)%",
                    value: Binding(get: { Double(model.styleIntensity) }, set: { model.setStyleIntensity(Int($0.rounded())) }),
                    range: 0...100
                )
                .disabled(model.styleName == "Custom")
                .opacity(model.styleName == "Custom" ? 0.55 : 1)

                DoubleControlSlider(
                    title: "Volume",
                    valueText: "\(Int(model.controls.gainDb)) dB",
                    value: Binding(get: { model.controls.gainDb }, set: { model.setControl(\.gainDb, $0) }),
                    range: -12...12
                )

                DoubleControlSlider(
                    title: "Target Loudness",
                    valueText: "\(Int(model.controls.targetLufs)) LUFS",
                    value: Binding(get: { model.controls.targetLufs }, set: { model.setControl(\.targetLufs, $0) }),
                    range: -24...0
                )

                IntControlSlider(title: "Clarity", keyPath: \.clarityPercent, suffix: "%")
                IntControlSlider(title: "Bass", keyPath: \.bassPercent, suffix: "%")
                IntControlSlider(title: "Treble", keyPath: \.treblePercent, suffix: "%")
                IntControlSlider(title: "Punch", keyPath: \.punchPercent, suffix: "%")
                IntControlSlider(title: "Stereo Width", keyPath: \.stereoWidthPercent, suffix: "%")
                IntControlSlider(title: "Low Cut", keyPath: \.lowCutHz, suffix: " Hz", range: 20...80)
                IntControlSlider(title: "High Cut", keyPath: \.highCutHz, suffix: " Hz", range: 6000...20_000)

                Toggle("Peak Safety", isOn: Binding(get: { model.controls.truePeakLimiter }, set: { model.setControl(\.truePeakLimiter, $0) }))
                Toggle("Tone Fix", isOn: Binding(get: { model.controls.autoEq }, set: { model.setControl(\.autoEq, $0) }))

                Text("Saved Settings")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Color.masteryMuted)

                Picker("Memories", selection: Binding(get: { model.selectedMemoryName }, set: { model.selectedMemoryName = $0; model.loadMemory(named: $0) })) {
                    Text("Memories").tag("Memories")
                    ForEach(model.memoryNames, id: \.self) { name in
                        Text(name).tag(name)
                    }
                }
                .labelsHidden()

                HStack {
                    TextField("Memory name", text: $memoryName)
                        .textFieldStyle(.roundedBorder)
                    Button("Save") {
                        model.saveMemory(named: memoryName)
                        memoryName = ""
                    }
                    .buttonStyle(GhostButtonStyle())
                }

                HStack {
                    Spacer()
                    Button("Undo") {
                        model.undoControlChanges()
                    }
                    .buttonStyle(GhostButtonStyle())
                }
            }
            .padding(22)
        }
        .background(Color.masteryPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
    }
}

private struct ManualSidebarPlaceholder: View {
    @EnvironmentObject private var model: MasteringViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Mastering")
                .font(.title3.weight(.bold))

            Text(model.trackURLs.isEmpty ? "Upload a track" : "Loading track")
                .font(.headline)
                .foregroundStyle(Color.masteryMuted)

            if !model.trackURLs.isEmpty {
                ProgressView()
                    .progressViewStyle(.circular)
                    .controlSize(.small)
            }

            Spacer()
        }
        .padding(22)
        .frame(maxHeight: .infinity, alignment: .topLeading)
        .background(Color.masteryPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
    }
}

private struct IntControlSlider: View {
    @EnvironmentObject private var model: MasteringViewModel
    var title: String
    var keyPath: WritableKeyPath<MasteringControls, Int>
    var suffix: String
    var range: ClosedRange<Double> = 0...100

    var body: some View {
        ControlSlider(
            title: title,
            valueText: "\(model.controls[keyPath: keyPath])\(suffix)",
            value: Binding(
                get: { Double(model.controls[keyPath: keyPath]) },
                set: { model.setControl(keyPath, Int($0.rounded())) }
            ),
            range: range
        )
    }
}

private struct DoubleControlSlider: View {
    var title: String
    var valueText: String
    var value: Binding<Double>
    var range: ClosedRange<Double>

    var body: some View {
        ControlSlider(title: title, valueText: valueText, value: value, range: range)
    }
}

private struct ControlSlider: View {
    var title: String
    var valueText: String
    var value: Binding<Double>
    var range: ClosedRange<Double>

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                Text(valueText)
                    .foregroundStyle(Color.masteryMuted)
            }
            Slider(value: value, in: range, step: 1)
        }
    }
}
