import Foundation
import SwiftUI
import UniformTypeIdentifiers

let masteryAudioTypes: [UTType] = ["wav", "mp3", "flac"].compactMap { UTType(filenameExtension: $0) }

extension Color {
    static let masteryBackground = Color(red: 0.02, green: 0.02, blue: 0.025)
    static let masteryPanel = Color(red: 0.055, green: 0.058, blue: 0.067)
    static let masteryRaisedPanel = Color(red: 0.07, green: 0.075, blue: 0.09)
    static let masteryBorder = Color(red: 0.16, green: 0.17, blue: 0.19)
    static let masteryText = Color(red: 0.96, green: 0.95, blue: 0.93)
    static let masteryMuted = Color(red: 0.55, green: 0.57, blue: 0.61)
    static let masteryAccent = Color(red: 1.0, green: 0.35, blue: 0.21)
    static let masteryBlue = Color(red: 0.47, green: 0.72, blue: 1.0)
}

struct AudioDropZone: View {
    var title: String
    var emptyText: String
    var buttonText: String
    var allowsMultipleSelection: Bool
    var onURLs: ([URL]) -> Void

    @State private var isFileImporterPresented = false
    @State private var isTargeted = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.title3.weight(.bold))

            VStack(spacing: 12) {
                Image(systemName: "arrow.up.doc")
                    .font(.system(size: 34, weight: .bold))
                    .foregroundStyle(Color.masteryMuted)
                    .frame(width: 76, height: 76)
                    .background(Color.white.opacity(0.04))
                    .clipShape(RoundedRectangle(cornerRadius: 8))

                Text(emptyText)
                    .font(.title3.weight(.semibold))
                    .lineLimit(2)
                    .multilineTextAlignment(.center)

                Button(buttonText) {
                    isFileImporterPresented = true
                }
                .buttonStyle(GhostButtonStyle())
            }
            .frame(maxWidth: .infinity, minHeight: 220)
            .padding(18)
            .background(Color.black.opacity(0.28))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(isTargeted ? Color.masteryAccent : Color.masteryBorder, style: StrokeStyle(lineWidth: 2, dash: [7, 6]))
            )
            .onDrop(of: [UTType.fileURL.identifier], isTargeted: $isTargeted, perform: loadDroppedFiles)
        }
        .padding(22)
        .frame(maxWidth: .infinity)
        .background(Color.masteryPanel)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
        .fileImporter(
            isPresented: $isFileImporterPresented,
            allowedContentTypes: masteryAudioTypes,
            allowsMultipleSelection: allowsMultipleSelection
        ) { result in
            if case let .success(urls) = result {
                onURLs(urls)
            }
        }
    }

    private func loadDroppedFiles(_ providers: [NSItemProvider]) -> Bool {
        let matchingProviders = providers.filter {
            $0.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier)
        }
        guard !matchingProviders.isEmpty else {
            return false
        }

        let lock = NSLock()
        let group = DispatchGroup()
        var urls: [URL] = []

        for provider in matchingProviders {
            group.enter()
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
                defer { group.leave() }

                let url: URL?
                if let data = item as? Data {
                    url = URL(dataRepresentation: data, relativeTo: nil)
                } else if let itemURL = item as? URL {
                    url = itemURL
                } else if let itemURL = item as? NSURL {
                    url = itemURL as URL
                } else {
                    url = nil
                }

                guard let url else {
                    return
                }

                lock.lock()
                urls.append(url)
                lock.unlock()
            }
        }

        group.notify(queue: .main) {
            if !urls.isEmpty {
                onURLs(urls)
            }
        }

        return true
    }
}

struct WaveformView: View {
    var peaks: [Float]
    var accent: Color
    var active: Bool
    var displayText: String
    var playheadProgress: Double

    var body: some View {
        Canvas { context, size in
            let rect = CGRect(origin: .zero, size: size)
            context.fill(Path(rect), with: .color(Color(red: 0.06, green: 0.065, blue: 0.078)))

            var centerLine = Path()
            centerLine.move(to: CGPoint(x: 0, y: size.height / 2))
            centerLine.addLine(to: CGPoint(x: size.width, y: size.height / 2))
            context.stroke(centerLine, with: .color(Color.masteryBorder), lineWidth: 1)

            if peaks.isEmpty {
                let borderPath = Path(roundedRect: rect.insetBy(dx: 1, dy: 1), cornerRadius: 8)
                context.stroke(borderPath, with: .color(Color.masteryBorder), lineWidth: 2)
                return
            }

            let barWidth = max(2.0, size.width / CGFloat(max(1, peaks.count)))
            let barColor = active ? accent : Color(red: 0.30, green: 0.33, blue: 0.38)

            for (index, peak) in peaks.enumerated() {
                let normalized = max(0.02, min(1.0, CGFloat(peak)))
                let height = normalized * (size.height * 0.42)
                let x = CGFloat(index) * barWidth
                let barRect = CGRect(
                    x: x,
                    y: (size.height / 2) - height,
                    width: max(1.0, barWidth - 1.0),
                    height: height * 2.0
                )
                context.fill(Path(roundedRect: barRect, cornerRadius: 2), with: .color(barColor))
            }

            let outline = Path(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), cornerRadius: 8)
            context.stroke(outline, with: .color(active ? accent : Color.masteryBorder), lineWidth: 1)

            if !displayText.isEmpty {
                let text = Text(displayText)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundColor(.white)
                context.draw(text, at: CGPoint(x: 16, y: size.height / 2), anchor: .leading)
            }

            let playheadX = CGFloat(max(0.0, min(1.0, playheadProgress))) * max(1.0, size.width - 1.0)
            var playhead = Path()
            playhead.move(to: CGPoint(x: playheadX, y: 4))
            playhead.addLine(to: CGPoint(x: playheadX, y: size.height - 4))
            context.stroke(playhead, with: .color(.white), lineWidth: 2)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct AccentButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(Color.black)
            .padding(.horizontal, 20)
            .frame(minHeight: 42)
            .background(Color.masteryAccent.opacity(configuration.isPressed ? 0.78 : 1.0))
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct GhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(Color.white)
            .padding(.horizontal, 16)
            .frame(minHeight: 38)
            .background(Color.white.opacity(configuration.isPressed ? 0.12 : 0.06))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.masteryBorder, lineWidth: 1))
    }
}

struct ChipButtonStyle: ButtonStyle {
    var isSelected: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(isSelected ? Color.black : Color.white)
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(isSelected ? Color.masteryAccent : Color.white.opacity(configuration.isPressed ? 0.12 : 0.06))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(isSelected ? Color.masteryAccent : Color.masteryBorder, lineWidth: 1))
    }
}

struct SourceButtonStyle: ButtonStyle {
    var isActive: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline.weight(.bold))
            .foregroundStyle(isActive ? Color.black : Color.masteryMuted)
            .frame(width: 44, height: 36)
            .background(isActive ? Color.masteryAccent : Color.white.opacity(configuration.isPressed ? 0.12 : 0.06))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(isActive ? Color.masteryAccent : Color.masteryBorder, lineWidth: 1))
    }
}
