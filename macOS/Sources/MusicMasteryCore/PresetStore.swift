import Foundation

public struct MasteringPresetStore: Sendable {
    public let url: URL

    public init(url: URL? = nil) {
        self.url = url ?? Self.defaultPresetURL()
    }

    public static func defaultPresetURL() -> URL {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support", isDirectory: true)
        return appSupport
            .appendingPathComponent("Music Mastery", isDirectory: true)
            .appendingPathComponent("presets.json")
    }

    public func listNames() -> [String] {
        readPayload().keys.sorted()
    }

    public func loadPreset(named name: String) -> MasteringControls? {
        readPayload()[name]
    }

    public func savePreset(named name: String, controls: MasteringControls) throws {
        let cleanedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanedName.isEmpty else {
            throw PresetStoreError.emptyName
        }

        var payload = readPayload()
        payload[cleanedName] = controls
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder.prettySorted.encode(payload)
        try data.write(to: url, options: .atomic)
    }

    private func readPayload() -> [String: MasteringControls] {
        guard let data = try? Data(contentsOf: url) else {
            return [:]
        }
        return (try? JSONDecoder().decode([String: MasteringControls].self, from: data)) ?? [:]
    }
}

public enum PresetStoreError: Error {
    case emptyName
}

private extension JSONEncoder {
    static var prettySorted: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
