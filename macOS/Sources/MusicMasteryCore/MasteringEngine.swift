import AVFoundation
import Foundation

public let defaultSampleRate = 44_100.0
public let defaultChannelCount: AVAudioChannelCount = 2

public struct StereoAudio: Equatable, Sendable {
    public var sampleRate: Double
    public var left: [Float]
    public var right: [Float]

    public init(sampleRate: Double = defaultSampleRate, left: [Float], right: [Float]) {
        let frameCount = min(left.count, right.count)
        self.sampleRate = sampleRate
        self.left = Array(left.prefix(frameCount))
        self.right = Array(right.prefix(frameCount))
    }

    public var frameCount: Int {
        min(left.count, right.count)
    }

    public var isEmpty: Bool {
        frameCount == 0
    }
}

public struct LiveAudioTrack: Sendable {
    public var url: URL
    public var sampleRate: Double
    public var originalAudio: StereoAudio
    public var masteredAudio: StereoAudio
    public var originalWaveform: [Float]
    public var masteredWaveform: [Float]
    public var sourceLevelDb: Double
    public var estimatedBpm: Double?

    public init(
        url: URL,
        sampleRate: Double,
        originalAudio: StereoAudio,
        masteredAudio: StereoAudio,
        originalWaveform: [Float],
        masteredWaveform: [Float],
        sourceLevelDb: Double,
        estimatedBpm: Double?
    ) {
        self.url = url
        self.sampleRate = sampleRate
        self.originalAudio = originalAudio
        self.masteredAudio = masteredAudio
        self.originalWaveform = originalWaveform
        self.masteredWaveform = masteredWaveform
        self.sourceLevelDb = sourceLevelDb
        self.estimatedBpm = estimatedBpm
    }
}

public enum MasteringEngineError: LocalizedError {
    case emptyAudio
    case unsupportedAudioBuffer
    case conversionFailed
    case invalidBitDepth(Int)

    public var errorDescription: String? {
        switch self {
        case .emptyAudio:
            return "The audio file did not contain readable audio."
        case .unsupportedAudioBuffer:
            return "The audio buffer could not be read."
        case .conversionFailed:
            return "The audio file could not be converted for mastering."
        case .invalidBitDepth(let bitDepth):
            return "Unsupported bit depth: \(bitDepth)."
        }
    }
}

public enum AudioMasteringEngine {
    public static func decodeAudioFile(_ url: URL, sampleRate: Double = defaultSampleRate) throws -> StereoAudio {
        let inputFile = try AVAudioFile(forReading: url)
        let inputFormat = inputFile.processingFormat
        let inputCapacity = AVAudioFrameCount(max(1, min(Int64(UInt32.max), inputFile.length)))

        guard let inputBuffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: inputCapacity) else {
            throw MasteringEngineError.unsupportedAudioBuffer
        }
        try inputFile.read(into: inputBuffer)

        guard inputBuffer.frameLength > 0 else {
            throw MasteringEngineError.emptyAudio
        }

        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: defaultChannelCount,
            interleaved: false
        ) else {
            throw MasteringEngineError.conversionFailed
        }

        let needsConversion = inputFormat.commonFormat != .pcmFormatFloat32
            || inputFormat.sampleRate != sampleRate
            || inputFormat.channelCount != defaultChannelCount
            || inputFormat.isInterleaved

        if !needsConversion {
            return try stereoAudio(from: inputBuffer, sampleRate: sampleRate)
        }

        let ratio = sampleRate / max(1.0, inputFormat.sampleRate)
        let outputCapacity = AVAudioFrameCount(Double(inputBuffer.frameLength) * ratio) + 4096
        guard
            let outputBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: outputCapacity),
            let converter = AVAudioConverter(from: inputFormat, to: targetFormat)
        else {
            throw MasteringEngineError.conversionFailed
        }

        var deliveredInput = false
        let inputBlock: AVAudioConverterInputBlock = { _, status in
            if deliveredInput {
                status.pointee = .noDataNow
                return nil
            }
            deliveredInput = true
            status.pointee = .haveData
            return inputBuffer
        }

        var conversionError: NSError?
        let status = converter.convert(to: outputBuffer, error: &conversionError, withInputFrom: inputBlock)
        if let conversionError {
            throw conversionError
        }
        guard status != .error, outputBuffer.frameLength > 0 else {
            throw MasteringEngineError.conversionFailed
        }

        return try stereoAudio(from: outputBuffer, sampleRate: sampleRate)
    }

    public static func writeWAV(_ audio: StereoAudio, to url: URL, bitDepth: Int = 16) throws {
        guard [16, 24, 32].contains(bitDepth) else {
            throw MasteringEngineError.invalidBitDepth(bitDepth)
        }

        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)

        guard let bufferFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: audio.sampleRate,
            channels: defaultChannelCount,
            interleaved: false
        ) else {
            throw MasteringEngineError.conversionFailed
        }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: bufferFormat,
            frameCapacity: AVAudioFrameCount(audio.frameCount)
        ) else {
            throw MasteringEngineError.unsupportedAudioBuffer
        }
        buffer.frameLength = AVAudioFrameCount(audio.frameCount)

        guard let channels = buffer.floatChannelData else {
            throw MasteringEngineError.unsupportedAudioBuffer
        }
        channels[0].update(from: audio.left, count: audio.frameCount)
        channels[1].update(from: audio.right, count: audio.frameCount)

        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: audio.sampleRate,
            AVNumberOfChannelsKey: Int(defaultChannelCount),
            AVLinearPCMBitDepthKey: bitDepth,
            AVLinearPCMIsFloatKey: bitDepth == 32,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false
        ]

        let outputFile = try AVAudioFile(
            forWriting: url,
            settings: settings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
        try outputFile.write(from: buffer)
    }

    public static func loadLiveAudioTrack(_ url: URL, waveformPoints: Int = 240) throws -> LiveAudioTrack {
        let originalAudio = try decodeAudioFile(url)
        let sourceLevelDb = measureAudioLevelDb(originalAudio)
        let waveform = buildWaveformPeaks(originalAudio, points: waveformPoints)
        return LiveAudioTrack(
            url: url,
            sampleRate: originalAudio.sampleRate,
            originalAudio: originalAudio,
            masteredAudio: originalAudio,
            originalWaveform: waveform,
            masteredWaveform: waveform,
            sourceLevelDb: sourceLevelDb,
            estimatedBpm: estimateBpm(originalAudio)
        )
    }

    public static func runManualMastering(
        inputURLs: [URL],
        outputDirectory: URL,
        controls: MasteringControls,
        preview: Bool = true
    ) throws -> [URL] {
        let outputURLs = preview
            ? buildPreviewOutputURLs(inputURLs: inputURLs, outputDirectory: outputDirectory)
            : buildOutputURLs(inputURLs: inputURLs, outputDirectory: outputDirectory)
        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

        for (inputURL, outputURL) in zip(inputURLs, outputURLs) {
            let audio = try decodeAudioFile(inputURL)
            let sourceLevelDb = measureAudioLevelDb(audio)
            let mastered = applyLiveMastering(audio, controls: controls, sourceLevelDb: sourceLevelDb)
            try writeWAV(mastered, to: outputURL, bitDepth: 16)
        }

        return outputURLs
    }

    public static func runReferenceMatch(
        inputURLs: [URL],
        referenceURL: URL,
        outputDirectory: URL,
        controls: MasteringControls,
        preview: Bool = true
    ) throws -> [URL] {
        let referenceAudio = try decodeAudioFile(referenceURL)
        let outputURLs = preview
            ? buildPreviewOutputURLs(inputURLs: inputURLs, outputDirectory: outputDirectory)
            : buildOutputURLs(inputURLs: inputURLs, outputDirectory: outputDirectory)
        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)

        for (inputURL, outputURL) in zip(inputURLs, outputURLs) {
            let targetAudio = try decodeAudioFile(inputURL)
            let mastered = referenceMatch(
                target: targetAudio,
                reference: referenceAudio,
                controls: controls
            )
            try writeWAV(mastered, to: outputURL, bitDepth: controls.bitDepth)
        }

        return outputURLs
    }

    public static func saveMasteredPreviews(
        previewURLs: [URL],
        sourceURLs: [URL],
        outputDirectory: URL
    ) throws -> [URL] {
        guard previewURLs.count == sourceURLs.count else {
            throw MasteringEngineError.conversionFailed
        }

        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
        let savedURLs = buildOutputURLs(inputURLs: sourceURLs, outputDirectory: outputDirectory)

        for (previewURL, savedURL) in zip(previewURLs, savedURLs) {
            if FileManager.default.fileExists(atPath: savedURL.path) {
                try FileManager.default.removeItem(at: savedURL)
            }
            try FileManager.default.copyItem(at: previewURL, to: savedURL)
        }

        return savedURLs
    }

    public static func measureAudioLevelDb(_ audio: StereoAudio) -> Double {
        guard !audio.isEmpty else {
            return -24.0
        }

        var sum = 0.0
        for index in 0..<audio.frameCount {
            let left = Double(audio.left[index])
            let right = Double(audio.right[index])
            sum += left * left
            sum += right * right
        }

        let rms = sqrt(sum / Double(audio.frameCount * 2))
        guard rms > 1e-8 else {
            return -24.0
        }
        return 20.0 * log10(rms)
    }

    public static func buildWaveformPeaks(_ audio: StereoAudio, points: Int = 240) -> [Float] {
        guard points > 0 else {
            return []
        }
        guard !audio.isEmpty else {
            return Array(repeating: 0.0, count: points)
        }

        let framesPerBucket = max(1, Int(ceil(Double(audio.frameCount) / Double(points))))
        var peaks: [Float] = []
        peaks.reserveCapacity(points)

        for index in 0..<points {
            let start = index * framesPerBucket
            let end = min(audio.frameCount, start + framesPerBucket)
            if start >= audio.frameCount {
                peaks.append(0.0)
                continue
            }

            var peak: Float = 0.0
            for frameIndex in start..<end {
                peak = max(peak, abs(audio.left[frameIndex]), abs(audio.right[frameIndex]))
            }
            peaks.append(min(1.0, peak))
        }

        return peaks
    }

    public static func applyLiveMastering(
        _ audio: StereoAudio,
        controls: MasteringControls,
        sourceLevelDb: Double,
        sampleRate: Double = defaultSampleRate
    ) -> StereoAudio {
        guard !audio.isEmpty else {
            return StereoAudio(sampleRate: sampleRate, left: [], right: [])
        }

        var processed = audio
        processed.sampleRate = sampleRate

        let cleanupCutoff = max(20, min(80, controls.lowCutHz))
        if cleanupCutoff > 20 {
            processed = applyBiquad(processed, coefficients: highPassCoefficients(sampleRate: sampleRate, frequency: Double(cleanupCutoff)))
        }

        let bassGain = MasteringControls.centeredGain(controls.bassPercent, maxGainDb: 6.0)
        if abs(bassGain) >= 0.1 {
            processed = applyBiquad(processed, coefficients: lowShelfCoefficients(sampleRate: sampleRate, frequency: 100.0, gainDb: bassGain))
        }

        let voiceGain = MasteringControls.centeredGain(controls.clarityPercent, maxGainDb: 4.0)
        if abs(voiceGain) >= 0.1 {
            processed = applyBiquad(processed, coefficients: peakingCoefficients(sampleRate: sampleRate, frequency: 2500.0, q: 1.2, gainDb: voiceGain))
        }

        let mudCut = -max(0.0, (Double(controls.clarityPercent) - 50.0) / 50.0 * 2.0)
        if abs(mudCut) >= 0.1 {
            processed = applyBiquad(processed, coefficients: peakingCoefficients(sampleRate: sampleRate, frequency: 320.0, q: 1.0, gainDb: mudCut))
        }

        let trebleGain = MasteringControls.centeredGain(controls.treblePercent, maxGainDb: 5.0)
        if abs(trebleGain) >= 0.1 {
            processed = applyBiquad(processed, coefficients: highShelfCoefficients(sampleRate: sampleRate, frequency: 4500.0, gainDb: trebleGain))
        }

        let highCut = max(6000, min(20_000, controls.highCutHz))
        if highCut < 20_000 {
            processed = applyBiquad(processed, coefficients: lowPassCoefficients(sampleRate: sampleRate, frequency: Double(highCut)))
        }

        if controls.autoEq {
            processed = applyBiquad(processed, coefficients: peakingCoefficients(sampleRate: sampleRate, frequency: 180.0, q: 1.0, gainDb: -1.0))
            processed = applyBiquad(processed, coefficients: peakingCoefficients(sampleRate: sampleRate, frequency: 4200.0, q: 1.0, gainDb: 1.2))
        }

        processed = applyPunch(processed, percent: controls.punchPercent)
        processed = applyStereoWidth(processed, percent: controls.stereoWidthPercent)
        processed = matchTargetLevel(processed, targetDb: controls.targetLufs, sourceLevelDb: sourceLevelDb)

        if abs(controls.gainDb) >= 0.05 {
            processed = applyGain(processed, gainDb: controls.gainDb)
        }

        if controls.truePeakLimiter {
            processed = applyTruePeakLimiter(processed)
        } else {
            processed = clipped(processed)
        }

        return processed
    }

    public static func referenceMatch(
        target: StereoAudio,
        reference: StereoAudio,
        controls: MasteringControls
    ) -> StereoAudio {
        let targetLevel = measureAudioLevelDb(target)
        var working = applyLiveMastering(target, controls: controls, sourceLevelDb: targetLevel)

        let referenceLevel = measureAudioLevelDb(reference)
        let workingLevel = measureAudioLevelDb(working)
        working = applyGain(working, gainDb: max(-12.0, min(12.0, referenceLevel - workingLevel)))

        let targetTone = tonalBalance(working)
        let referenceTone = tonalBalance(reference)
        let lowDelta = max(-4.0, min(4.0, referenceTone.low - targetTone.low))
        let midDelta = max(-3.0, min(3.0, referenceTone.mid - targetTone.mid))
        let highDelta = max(-4.0, min(4.0, referenceTone.high - targetTone.high))

        if abs(lowDelta) >= 0.25 {
            working = applyBiquad(working, coefficients: lowShelfCoefficients(sampleRate: working.sampleRate, frequency: 120.0, gainDb: lowDelta))
        }
        if abs(midDelta) >= 0.25 {
            working = applyBiquad(working, coefficients: peakingCoefficients(sampleRate: working.sampleRate, frequency: 1500.0, q: 0.9, gainDb: midDelta))
        }
        if abs(highDelta) >= 0.25 {
            working = applyBiquad(working, coefficients: highShelfCoefficients(sampleRate: working.sampleRate, frequency: 4500.0, gainDb: highDelta))
        }

        working = controls.truePeakLimiter ? applyTruePeakLimiter(working, ceiling: 0.97) : clipped(working)

        let (dry, wet) = referenceStrengthWeights(controls.referenceStrengthPercent)
        return blend(original: target, mastered: working, dry: Float(dry), wet: Float(wet))
    }

    public static func estimateBpm(_ audio: StereoAudio, sampleRate: Double = defaultSampleRate) -> Double? {
        guard !audio.isEmpty, audio.frameCount >= Int(sampleRate * 4.0) else {
            return nil
        }

        let hop = 1024
        let usable = audio.frameCount - (audio.frameCount % hop)
        guard usable > hop * 8 else {
            return nil
        }

        var envelope: [Double] = []
        envelope.reserveCapacity(usable / hop)
        var frame = 0
        while frame < usable {
            var bucket = 0.0
            for index in frame..<(frame + hop) {
                bucket += (abs(Double(audio.left[index])) + abs(Double(audio.right[index]))) * 0.5
            }
            envelope.append(bucket / Double(hop))
            frame += hop
        }

        guard let first = envelope.first else {
            return nil
        }
        var onset = envelope.map { max(0.0, $0 - first) }
        for index in stride(from: onset.count - 1, through: 1, by: -1) {
            onset[index] = max(0.0, envelope[index] - envelope[index - 1])
        }

        let mean = onset.reduce(0.0, +) / Double(onset.count)
        onset = onset.map { $0 - mean }
        guard onset.contains(where: { $0 > 0 }) else {
            return nil
        }

        let frameRate = sampleRate / Double(hop)
        let minBpm = 70.0
        let maxBpm = 180.0
        let minLag = Int(frameRate * 60.0 / maxBpm)
        let maxLag = Int(frameRate * 60.0 / minBpm)
        guard maxLag > minLag else {
            return nil
        }

        var bestLag = minLag
        var bestScore = -Double.infinity
        for lag in minLag...maxLag {
            var score = 0.0
            for index in 0..<(onset.count - lag) {
                score += onset[index] * onset[index + lag]
            }
            if score > bestScore {
                bestScore = score
                bestLag = lag
            }
        }

        guard bestLag > 0 else {
            return nil
        }
        return (60.0 * frameRate / Double(bestLag) * 10.0).rounded() / 10.0
    }
}

private extension AudioMasteringEngine {
    static func stereoAudio(from buffer: AVAudioPCMBuffer, sampleRate: Double) throws -> StereoAudio {
        guard let channelData = buffer.floatChannelData else {
            throw MasteringEngineError.unsupportedAudioBuffer
        }

        let frames = Int(buffer.frameLength)
        guard frames > 0 else {
            throw MasteringEngineError.emptyAudio
        }

        let left = Array(UnsafeBufferPointer(start: channelData[0], count: frames))
        let right: [Float]
        if Int(buffer.format.channelCount) > 1 {
            right = Array(UnsafeBufferPointer(start: channelData[1], count: frames))
        } else {
            right = left
        }

        return StereoAudio(sampleRate: sampleRate, left: left, right: right)
    }

    static func applyGain(_ audio: StereoAudio, gainDb: Double) -> StereoAudio {
        let gain = Float(pow(10.0, gainDb / 20.0))
        return StereoAudio(
            sampleRate: audio.sampleRate,
            left: audio.left.map { $0 * gain },
            right: audio.right.map { $0 * gain }
        )
    }

    static func matchTargetLevel(_ audio: StereoAudio, targetDb: Double, sourceLevelDb: Double) -> StereoAudio {
        let measuredDb = measureAudioLevelDb(audio)
        if abs(targetDb - sourceLevelDb) < 0.05, abs(measuredDb - sourceLevelDb) < 0.05 {
            return audio
        }

        return applyGain(audio, gainDb: targetDb - measuredDb)
    }

    static func applyTruePeakLimiter(
        _ audio: StereoAudio,
        ceiling: Float = 0.98,
        kneeStart: Float = 0.80
    ) -> StereoAudio {
        var peak: Float = 0.0
        for index in 0..<audio.frameCount {
            peak = max(peak, abs(audio.left[index]), abs(audio.right[index]))
        }

        let threshold = ceiling * kneeStart
        guard peak > threshold else {
            return audio
        }

        let kneeWidth = max(0.000001, ceiling - threshold)
        func limitSample(_ sample: Float) -> Float {
            let magnitude = abs(sample)
            guard magnitude > threshold else {
                return sample
            }
            let excess = magnitude - threshold
            let compressed = threshold + kneeWidth * tanh(excess / kneeWidth)
            return sample.sign == .minus ? -compressed : compressed
        }

        var limited = StereoAudio(
            sampleRate: audio.sampleRate,
            left: audio.left.map(limitSample),
            right: audio.right.map(limitSample)
        )

        var limitedPeak: Float = 0.0
        for index in 0..<limited.frameCount {
            limitedPeak = max(limitedPeak, abs(limited.left[index]), abs(limited.right[index]))
        }
        if limitedPeak > ceiling {
            let scale = ceiling / limitedPeak
            limited.left = limited.left.map { $0 * scale }
            limited.right = limited.right.map { $0 * scale }
        }
        return limited
    }

    static func clipped(_ audio: StereoAudio) -> StereoAudio {
        StereoAudio(
            sampleRate: audio.sampleRate,
            left: audio.left.map { min(1.0, max(-1.0, $0)) },
            right: audio.right.map { min(1.0, max(-1.0, $0)) }
        )
    }

    static func applyPunch(_ audio: StereoAudio, percent: Int) -> StereoAudio {
        let amount = Float(max(0.0, min(100.0, Double(percent))) / 100.0)
        guard abs(amount - 0.5) >= 0.01 else {
            return audio
        }

        if amount >= 0.5 {
            let drive = 1.0 + max(0.0, amount - 0.5) * 1.8
            let mix = (amount - 0.5) * 2.0
            func process(_ sample: Float) -> Float {
                let softened = tanh(sample * drive) / drive
                return ((1.0 - mix) * sample) + (mix * softened)
            }
            return StereoAudio(sampleRate: audio.sampleRate, left: audio.left.map(process), right: audio.right.map(process))
        }

        let smoothMix = (0.5 - amount) * 2.0
        func process(_ sample: Float) -> Float {
            ((1.0 - smoothMix) * sample) + (smoothMix * (sample * 0.92))
        }
        return StereoAudio(sampleRate: audio.sampleRate, left: audio.left.map(process), right: audio.right.map(process))
    }

    static func applyStereoWidth(_ audio: StereoAudio, percent: Int) -> StereoAudio {
        let clampedPercent = max(0, min(100, percent))
        let centeredPercent = (Double(clampedPercent) - 50.0) / 50.0
        let width = Float(1.0 + centeredPercent * 0.6)
        var left: [Float] = []
        var right: [Float] = []
        left.reserveCapacity(audio.frameCount)
        right.reserveCapacity(audio.frameCount)

        for index in 0..<audio.frameCount {
            let mid = (audio.left[index] + audio.right[index]) * 0.5
            let side = (audio.left[index] - audio.right[index]) * 0.5 * width
            left.append(mid + side)
            right.append(mid - side)
        }

        return StereoAudio(sampleRate: audio.sampleRate, left: left, right: right)
    }

    static func blend(original: StereoAudio, mastered: StereoAudio, dry: Float, wet: Float) -> StereoAudio {
        if wet >= 0.999 {
            return mastered
        }
        if wet <= 0.001 {
            return original
        }

        let frameCount = min(original.frameCount, mastered.frameCount)
        var left: [Float] = []
        var right: [Float] = []
        left.reserveCapacity(frameCount)
        right.reserveCapacity(frameCount)

        for index in 0..<frameCount {
            left.append(original.left[index] * dry + mastered.left[index] * wet)
            right.append(original.right[index] * dry + mastered.right[index] * wet)
        }

        return applyTruePeakLimiter(StereoAudio(sampleRate: original.sampleRate, left: left, right: right), ceiling: 0.97)
    }

    static func tonalBalance(_ audio: StereoAudio) -> (low: Double, mid: Double, high: Double) {
        let low = applyBiquad(audio, coefficients: lowPassCoefficients(sampleRate: audio.sampleRate, frequency: 180.0))
        let midLowCut = applyBiquad(audio, coefficients: highPassCoefficients(sampleRate: audio.sampleRate, frequency: 220.0))
        let mid = applyBiquad(midLowCut, coefficients: lowPassCoefficients(sampleRate: audio.sampleRate, frequency: 4200.0))
        let high = applyBiquad(audio, coefficients: highPassCoefficients(sampleRate: audio.sampleRate, frequency: 4200.0))
        return (
            measureAudioLevelDb(low),
            measureAudioLevelDb(mid),
            measureAudioLevelDb(high)
        )
    }
}

private struct BiquadCoefficients {
    var b0: Double
    var b1: Double
    var b2: Double
    var a0: Double
    var a1: Double
    var a2: Double
}

private extension AudioMasteringEngine {
    static func applyBiquad(_ audio: StereoAudio, coefficients: BiquadCoefficients) -> StereoAudio {
        StereoAudio(
            sampleRate: audio.sampleRate,
            left: filter(audio.left, coefficients: coefficients),
            right: filter(audio.right, coefficients: coefficients)
        )
    }

    static func filter(_ input: [Float], coefficients: BiquadCoefficients) -> [Float] {
        let b0 = coefficients.b0 / coefficients.a0
        let b1 = coefficients.b1 / coefficients.a0
        let b2 = coefficients.b2 / coefficients.a0
        let a1 = coefficients.a1 / coefficients.a0
        let a2 = coefficients.a2 / coefficients.a0

        var z1 = 0.0
        var z2 = 0.0
        var output: [Float] = []
        output.reserveCapacity(input.count)

        for sample in input {
            let x = Double(sample)
            let y = b0 * x + z1
            z1 = b1 * x - a1 * y + z2
            z2 = b2 * x - a2 * y
            output.append(Float(max(-8.0, min(8.0, y))))
        }

        return output
    }

    static func highPassCoefficients(sampleRate: Double, frequency: Double) -> BiquadCoefficients {
        let frequency = normalizedFrequency(frequency, sampleRate: sampleRate)
        let q = 1.0 / sqrt(2.0)
        let omega = 2.0 * Double.pi * frequency / sampleRate
        let alpha = sin(omega) / (2.0 * q)
        let cosOmega = cos(omega)
        return BiquadCoefficients(
            b0: (1.0 + cosOmega) / 2.0,
            b1: -(1.0 + cosOmega),
            b2: (1.0 + cosOmega) / 2.0,
            a0: 1.0 + alpha,
            a1: -2.0 * cosOmega,
            a2: 1.0 - alpha
        )
    }

    static func lowPassCoefficients(sampleRate: Double, frequency: Double) -> BiquadCoefficients {
        let frequency = normalizedFrequency(frequency, sampleRate: sampleRate)
        let q = 1.0 / sqrt(2.0)
        let omega = 2.0 * Double.pi * frequency / sampleRate
        let alpha = sin(omega) / (2.0 * q)
        let cosOmega = cos(omega)
        return BiquadCoefficients(
            b0: (1.0 - cosOmega) / 2.0,
            b1: 1.0 - cosOmega,
            b2: (1.0 - cosOmega) / 2.0,
            a0: 1.0 + alpha,
            a1: -2.0 * cosOmega,
            a2: 1.0 - alpha
        )
    }

    static func peakingCoefficients(sampleRate: Double, frequency: Double, q: Double, gainDb: Double) -> BiquadCoefficients {
        let frequency = normalizedFrequency(frequency, sampleRate: sampleRate)
        let a = pow(10.0, gainDb / 40.0)
        let omega = 2.0 * Double.pi * frequency / sampleRate
        let alpha = sin(omega) / (2.0 * q)
        let cosOmega = cos(omega)
        return BiquadCoefficients(
            b0: 1.0 + alpha * a,
            b1: -2.0 * cosOmega,
            b2: 1.0 - alpha * a,
            a0: 1.0 + alpha / a,
            a1: -2.0 * cosOmega,
            a2: 1.0 - alpha / a
        )
    }

    static func lowShelfCoefficients(sampleRate: Double, frequency: Double, gainDb: Double, slope: Double = 1.0) -> BiquadCoefficients {
        let frequency = normalizedFrequency(frequency, sampleRate: sampleRate)
        let a = pow(10.0, gainDb / 40.0)
        let omega = 2.0 * Double.pi * frequency / sampleRate
        let cosOmega = cos(omega)
        let sinOmega = sin(omega)
        let alpha = sinOmega / 2.0 * sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
        let beta = 2.0 * sqrt(a) * alpha
        return BiquadCoefficients(
            b0: a * ((a + 1.0) - (a - 1.0) * cosOmega + beta),
            b1: 2.0 * a * ((a - 1.0) - (a + 1.0) * cosOmega),
            b2: a * ((a + 1.0) - (a - 1.0) * cosOmega - beta),
            a0: (a + 1.0) + (a - 1.0) * cosOmega + beta,
            a1: -2.0 * ((a - 1.0) + (a + 1.0) * cosOmega),
            a2: (a + 1.0) + (a - 1.0) * cosOmega - beta
        )
    }

    static func highShelfCoefficients(sampleRate: Double, frequency: Double, gainDb: Double, slope: Double = 1.0) -> BiquadCoefficients {
        let frequency = normalizedFrequency(frequency, sampleRate: sampleRate)
        let a = pow(10.0, gainDb / 40.0)
        let omega = 2.0 * Double.pi * frequency / sampleRate
        let cosOmega = cos(omega)
        let sinOmega = sin(omega)
        let alpha = sinOmega / 2.0 * sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
        let beta = 2.0 * sqrt(a) * alpha
        return BiquadCoefficients(
            b0: a * ((a + 1.0) + (a - 1.0) * cosOmega + beta),
            b1: -2.0 * a * ((a - 1.0) + (a + 1.0) * cosOmega),
            b2: a * ((a + 1.0) + (a - 1.0) * cosOmega - beta),
            a0: (a + 1.0) - (a - 1.0) * cosOmega + beta,
            a1: 2.0 * ((a - 1.0) - (a + 1.0) * cosOmega),
            a2: (a + 1.0) - (a - 1.0) * cosOmega - beta
        )
    }

    static func normalizedFrequency(_ frequency: Double, sampleRate: Double) -> Double {
        max(10.0, min(sampleRate / 2.0 - 100.0, frequency))
    }
}
