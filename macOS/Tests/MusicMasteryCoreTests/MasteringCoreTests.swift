import XCTest
@testable import MusicMasteryCore

final class MasteringCoreTests: XCTestCase {
    func testSupportedAudioExtensionsMatchWindowsApp() {
        XCTAssertEqual(supportedAudioExtensions, [".wav", ".mp3", ".flac"])
    }

    func testAcceptedAudioURLsFilterAndDedupe() {
        let urls = [
            URL(fileURLWithPath: "/Music/one.wav"),
            URL(fileURLWithPath: "/Music/two.mp3"),
            URL(fileURLWithPath: "/Music/three.flac"),
            URL(fileURLWithPath: "/Music/ONE.wav"),
            URL(fileURLWithPath: "/Music/cover.png")
        ]

        let accepted = acceptedAudioURLs(urls)

        XCTAssertEqual(accepted.map(\.lastPathComponent), ["one.wav", "two.mp3", "three.flac"])
    }

    func testManualPreFilterUsesCurrentControlValues() {
        let controls = MasteringControls(
            gainDb: 1.5,
            clarityPercent: 75,
            bassPercent: 70,
            treblePercent: 65,
            punchPercent: 80,
            stereoWidthPercent: 70,
            lowCutHz: 32,
            highCutHz: 17_000,
            autoEq: true
        )

        let filterGraph = controls.manualPreFilter()

        XCTAssertTrue(filterGraph.contains("highpass=f=32"))
        XCTAssertTrue(filterGraph.contains("bass=g=2.4:f=100:w=0.8"))
        XCTAssertTrue(filterGraph.contains("equalizer=f=2500:t=q:w=1.2:g=2.0"))
        XCTAssertTrue(filterGraph.contains("treble=g=1.5:f=4500:w=0.6"))
        XCTAssertTrue(filterGraph.contains("acompressor="))
        XCTAssertTrue(filterGraph.contains("volume=1.5dB"))
        XCTAssertTrue(filterGraph.contains("extrastereo=m=1.20"))
    }

    func testStyledControlsAppliesWarmPresetWithIntensity() {
        let controls = styledControls(styleName: "Warm", intensityPercent: 50)

        XCTAssertLessThan(controls.clarityPercent, 50)
        XCTAssertGreaterThan(controls.bassPercent, 50)
        XCTAssertLessThan(controls.treblePercent, 50)
        XCTAssertGreaterThan(controls.targetLufs, -14.0)
    }

    func testBuildLoudnessMatchGainsReducesLouderVersion() {
        let (originalGain, masteredGain) = buildLoudnessMatchGains(originalDb: -15.0, masteredDb: -9.0)

        XCTAssertEqual(originalGain, 1.0)
        XCTAssertEqual((masteredGain * 100.0).rounded() / 100.0, 0.5)
    }

    func testReferenceStrengthWeightsFavorOriginalAtLowerStrength() {
        let (originalWeight, masteredWeight) = referenceStrengthWeights(25)

        XCTAssertEqual((originalWeight * 100.0).rounded() / 100.0, 0.75)
        XCTAssertEqual((masteredWeight * 100.0).rounded() / 100.0, 0.25)
    }

    func testWaveformPeakCount() {
        let audio = stereoTone()

        let peaks = AudioMasteringEngine.buildWaveformPeaks(audio, points: 64)

        XCTAssertEqual(peaks.count, 64)
        XCTAssertTrue(peaks.allSatisfy { $0 >= 0.0 && $0 <= 1.0 })
    }

    func testManualMasteringChangesToneAndKeepsPeakSafe() {
        let audio = stereoTone()
        let sourceLevel = AudioMasteringEngine.measureAudioLevelDb(audio)
        let controls = MasteringControls(
            targetLufs: sourceLevel + 1.5,
            clarityPercent: 80,
            bassPercent: 72,
            treblePercent: 65,
            punchPercent: 78,
            stereoWidthPercent: 65,
            lowCutHz: 28,
            autoEq: true
        )

        let processed = AudioMasteringEngine.applyLiveMastering(audio, controls: controls, sourceLevelDb: sourceLevel)

        XCTAssertEqual(processed.frameCount, audio.frameCount)
        XCTAssertFalse(zip(processed.left, audio.left).allSatisfy { abs($0 - $1) < 0.0001 })
        XCTAssertLessThanOrEqual(maxPeak(processed), 0.99)
    }

    func testOutputPathsUseMasterSuffix() {
        let outputs = buildOutputURLs(
            inputURLs: [URL(fileURLWithPath: "/music/one.wav"), URL(fileURLWithPath: "/music/two.mp3")],
            outputDirectory: URL(fileURLWithPath: "/exports", isDirectory: true)
        )

        XCTAssertEqual(outputs.map(\.path), ["/exports/one-master.wav", "/exports/two-master.wav"])
    }

    func testWavRoundTripAndReferencePreviewOutput() throws {
        let tempDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("music-mastery-core-tests-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock {
            try? FileManager.default.removeItem(at: tempDirectory)
        }

        let targetURL = tempDirectory.appendingPathComponent("target.wav")
        let referenceURL = tempDirectory.appendingPathComponent("reference.wav")
        let outputDirectory = tempDirectory.appendingPathComponent("out", isDirectory: true)

        try AudioMasteringEngine.writeWAV(stereoTone(), to: targetURL, bitDepth: 16)
        try AudioMasteringEngine.writeWAV(stereoTone(durationSeconds: 0.3), to: referenceURL, bitDepth: 16)

        let decoded = try AudioMasteringEngine.decodeAudioFile(targetURL)
        XCTAssertGreaterThan(decoded.frameCount, 0)

        let outputs = try AudioMasteringEngine.runReferenceMatch(
            inputURLs: [targetURL],
            referenceURL: referenceURL,
            outputDirectory: outputDirectory,
            controls: MasteringControls(referenceStrengthPercent: 50),
            preview: true
        )

        XCTAssertEqual(outputs.map(\.lastPathComponent), ["target-master-preview.wav"])
        XCTAssertTrue(FileManager.default.fileExists(atPath: outputs[0].path))
    }

    private func stereoTone(sampleRate: Double = 44_100.0, durationSeconds: Double = 0.25) -> StereoAudio {
        let frameCount = Int(sampleRate * durationSeconds)
        var left: [Float] = []
        var right: [Float] = []
        left.reserveCapacity(frameCount)
        right.reserveCapacity(frameCount)

        for index in 0..<frameCount {
            let time = Double(index) / sampleRate
            left.append(Float(0.35 * sin(2 * Double.pi * 120 * time) + 0.15 * sin(2 * Double.pi * 2600 * time)))
            right.append(Float(0.30 * sin(2 * Double.pi * 160 * time) + 0.12 * sin(2 * Double.pi * 4800 * time)))
        }

        return StereoAudio(sampleRate: sampleRate, left: left, right: right)
    }

    private func maxPeak(_ audio: StereoAudio) -> Float {
        var peak: Float = 0
        for index in 0..<audio.frameCount {
            peak = max(peak, abs(audio.left[index]), abs(audio.right[index]))
        }
        return peak
    }
}
