import Foundation

public let maxTrackCount = 10
public let supportedAudioExtensions: Set<String> = [".wav", ".mp3", ".flac"]

public func normalizePath(_ rawPath: String) -> String {
    URL(fileURLWithPath: rawPath).standardizedFileURL.path
}

public func dedupeKey(_ rawPath: String) -> String {
    normalizePath(rawPath).lowercased()
}

public func isSupportedAudioPath(_ rawPath: String) -> Bool {
    supportedAudioExtensions.contains(URL(fileURLWithPath: normalizePath(rawPath)).pathExtension.lowercased().prependDot)
}

public func acceptedAudioURLs(
    _ urls: [URL],
    maxItems: Int = maxTrackCount,
    existingURLs: [URL] = []
) -> [URL] {
    var accepted: [URL] = []
    var seen = Set(existingURLs.map { dedupeKey($0.path) })

    for url in urls {
        let normalized = url.standardizedFileURL
        let key = dedupeKey(normalized.path)

        guard isSupportedAudioPath(normalized.path), !seen.contains(key) else {
            continue
        }

        accepted.append(normalized)
        seen.insert(key)

        if accepted.count >= maxItems {
            break
        }
    }

    return accepted
}

public func buildPreviewOutputURLs(inputURLs: [URL], outputDirectory: URL) -> [URL] {
    inputURLs.map {
        outputDirectory.appendingPathComponent($0.deletingPathExtension().lastPathComponent + "-master-preview.wav")
    }
}

public func buildOutputURLs(inputURLs: [URL], outputDirectory: URL) -> [URL] {
    inputURLs.map {
        outputDirectory.appendingPathComponent($0.deletingPathExtension().lastPathComponent + "-master.wav")
    }
}

private extension String {
    var prependDot: String {
        hasPrefix(".") ? self : "." + self
    }
}
