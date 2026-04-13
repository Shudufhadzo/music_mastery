import Foundation

public struct MasteringControls: Codable, Equatable, Sendable {
    public var gainDb: Double
    public var targetLufs: Double
    public var clarityPercent: Int
    public var bassPercent: Int
    public var treblePercent: Int
    public var punchPercent: Int
    public var stereoWidthPercent: Int
    public var lowCutHz: Int
    public var highCutHz: Int
    public var truePeakLimiter: Bool
    public var autoEq: Bool
    public var bitDepth: Int
    public var referenceStrengthPercent: Int

    public init(
        gainDb: Double = 0.0,
        targetLufs: Double = -14.0,
        clarityPercent: Int = 50,
        bassPercent: Int = 50,
        treblePercent: Int = 50,
        punchPercent: Int = 50,
        stereoWidthPercent: Int = 50,
        lowCutHz: Int = 20,
        highCutHz: Int = 20_000,
        truePeakLimiter: Bool = true,
        autoEq: Bool = false,
        bitDepth: Int = 24,
        referenceStrengthPercent: Int = 100
    ) {
        self.gainDb = gainDb
        self.targetLufs = targetLufs
        self.clarityPercent = clarityPercent
        self.bassPercent = bassPercent
        self.treblePercent = treblePercent
        self.punchPercent = punchPercent
        self.stereoWidthPercent = stereoWidthPercent
        self.lowCutHz = lowCutHz
        self.highCutHz = highCutHz
        self.truePeakLimiter = truePeakLimiter
        self.autoEq = autoEq
        self.bitDepth = bitDepth
        self.referenceStrengthPercent = referenceStrengthPercent
    }

    public func manualPreFilter() -> String {
        var filters = ["highpass=f=\(Int(lowCutHz))"]

        let bassGain = Self.centeredGain(bassPercent, maxGainDb: 6.0)
        if abs(bassGain) >= 0.1 {
            filters.append(String(format: "bass=g=%.1f:f=100:w=0.8", bassGain))
        }

        let vocalGain = Self.centeredGain(clarityPercent, maxGainDb: 4.0)
        if abs(vocalGain) >= 0.1 {
            filters.append(String(format: "equalizer=f=2500:t=q:w=1.2:g=%.1f", vocalGain))
        }

        let vocalMudCut = -max(0.0, (Double(clarityPercent) - 50.0) / 50.0 * 2.0)
        if abs(vocalMudCut) >= 0.1 {
            filters.append(String(format: "equalizer=f=300:t=q:w=1.0:g=%.1f", vocalMudCut))
        }

        let trebleGain = Self.centeredGain(treblePercent, maxGainDb: 5.0)
        if abs(trebleGain) >= 0.1 {
            filters.append(String(format: "treble=g=%.1f:f=4500:w=0.6", trebleGain))
        }

        if autoEq {
            filters.append("equalizer=f=180:t=q:w=1.0:g=-1.0")
            filters.append("equalizer=f=4200:t=q:w=1.0:g=1.2")
        }

        let deesserIntensity = min(
            0.24,
            0.03
                + (Double(clarityPercent) / 100.0 * 0.07)
                + (Double(max(treblePercent - 50, 0)) / 50.0 * 0.04)
        )
        filters.append(String(format: "deesser=i=%.2f:m=0.50:f=0.55", deesserIntensity))

        let punchAmount = max(0.0, min(100.0, Double(punchPercent))) / 100.0
        let threshold = 0.22 - (punchAmount * 0.10)
        let ratio = 1.2 + (punchAmount * 1.6)
        let makeup = 1.0 + (punchAmount * 0.5)
        filters.append(
            String(
                format: "acompressor=threshold=%.3f:ratio=%.2f:attack=15:release=220:makeup=%.2f",
                threshold,
                ratio,
                makeup
            )
        )
        filters.append("lowpass=f=\(Int(highCutHz))")

        if gainDb != 0 {
            filters.append(String(format: "volume=%.1fdB", gainDb))
        }

        let stereoMultiplier = 1.0 + ((Double(stereoWidthPercent) - 50.0) / 100.0)
        if (stereoMultiplier * 100.0).rounded() / 100.0 != 1.0 {
            filters.append(String(format: "extrastereo=m=%.2f", stereoMultiplier))
        }

        return filters.joined(separator: ",")
    }

    public static func centeredGain(_ percent: Int, maxGainDb: Double) -> Double {
        let clamped = max(0, min(100, percent))
        return ((Double(clamped) - 50.0) / 50.0) * maxGainDb
    }
}

public let stylePresetTargets: [String: MasteringControls] = [
    "Clean": MasteringControls(
        targetLufs: -13.0,
        clarityPercent: 58,
        bassPercent: 48,
        treblePercent: 55,
        punchPercent: 45,
        stereoWidthPercent: 54,
        lowCutHz: 32,
        highCutHz: 18_800
    ),
    "Warm": MasteringControls(
        targetLufs: -12.0,
        clarityPercent: 42,
        bassPercent: 68,
        treblePercent: 38,
        punchPercent: 44,
        stereoWidthPercent: 46,
        lowCutHz: 24,
        highCutHz: 16_800
    ),
    "Punch": MasteringControls(
        targetLufs: -10.5,
        clarityPercent: 56,
        bassPercent: 60,
        treblePercent: 54,
        punchPercent: 82,
        stereoWidthPercent: 52,
        lowCutHz: 34,
        highCutHz: 18_200
    ),
    "Wide": MasteringControls(
        targetLufs: -12.0,
        clarityPercent: 50,
        bassPercent: 52,
        treblePercent: 52,
        punchPercent: 48,
        stereoWidthPercent: 78,
        lowCutHz: 30,
        highCutHz: 18_400
    ),
    "Vocal": MasteringControls(
        targetLufs: -11.5,
        clarityPercent: 88,
        bassPercent: 44,
        treblePercent: 70,
        punchPercent: 58,
        stereoWidthPercent: 58,
        lowCutHz: 40,
        highCutHz: 19_000
    ),
    "Bright": MasteringControls(
        targetLufs: -12.0,
        clarityPercent: 64,
        bassPercent: 44,
        treblePercent: 78,
        punchPercent: 48,
        stereoWidthPercent: 54,
        lowCutHz: 34,
        highCutHz: 19_600
    )
]

public func styledControls(styleName: String, intensityPercent: Int) -> MasteringControls {
    let base = MasteringControls()
    guard let target = stylePresetTargets[styleName] else {
        return base
    }

    let mix = max(0.0, min(100.0, Double(intensityPercent))) / 100.0

    func blend(_ baseValue: Double, _ targetValue: Double) -> Double {
        baseValue + (targetValue - baseValue) * mix
    }

    func blendInt(_ baseValue: Int, _ targetValue: Int) -> Int {
        Int(round(blend(Double(baseValue), Double(targetValue))))
    }

    return MasteringControls(
        gainDb: (blend(base.gainDb, target.gainDb) * 10.0).rounded() / 10.0,
        targetLufs: (blend(base.targetLufs, target.targetLufs) * 10.0).rounded() / 10.0,
        clarityPercent: blendInt(base.clarityPercent, target.clarityPercent),
        bassPercent: blendInt(base.bassPercent, target.bassPercent),
        treblePercent: blendInt(base.treblePercent, target.treblePercent),
        punchPercent: blendInt(base.punchPercent, target.punchPercent),
        stereoWidthPercent: blendInt(base.stereoWidthPercent, target.stereoWidthPercent),
        lowCutHz: blendInt(base.lowCutHz, target.lowCutHz),
        highCutHz: blendInt(base.highCutHz, target.highCutHz),
        truePeakLimiter: mix >= 0.5 ? target.truePeakLimiter : base.truePeakLimiter,
        autoEq: mix >= 0.5 ? target.autoEq : base.autoEq,
        bitDepth: base.bitDepth,
        referenceStrengthPercent: base.referenceStrengthPercent
    )
}

public func buildLoudnessMatchGains(originalDb: Double?, masteredDb: Double?) -> (Double, Double) {
    guard let originalDb, let masteredDb else {
        return (1.0, 1.0)
    }

    let targetDb = min(originalDb, masteredDb)
    let originalGain = min(1.0, max(0.15, pow(10.0, (targetDb - originalDb) / 20.0)))
    let masteredGain = min(1.0, max(0.15, pow(10.0, (targetDb - masteredDb) / 20.0)))
    return (originalGain, masteredGain)
}

public func referenceStrengthWeights(_ strengthPercent: Int) -> (Double, Double) {
    let wet = max(0.0, min(100.0, Double(strengthPercent))) / 100.0
    return (1.0 - wet, wet)
}
